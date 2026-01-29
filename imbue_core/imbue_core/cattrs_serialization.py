import abc
import asyncio
import base64
import builtins
import datetime
import functools
import importlib
import inspect
import json
from decimal import Decimal
from enum import Enum
from functools import cached_property
from functools import lru_cache
from functools import partial
from pathlib import Path
from pathlib import PosixPath
from types import NoneType
from types import UnionType
from typing import Any
from typing import Callable
from typing import ForwardRef
from typing import Hashable
from typing import Mapping
from typing import TypeVar
from typing import Union
from typing import cast
from typing import get_origin
from uuid import UUID

import anyio
import attr
from cachetools import LRUCache
from cattrs import Converter
from cattrs._compat import is_generic
from cattrs.gen import make_dict_unstructure_fn
from cattrs.gen import override
from httpx import URL
from humps import camelize  # pyre-ignore[21]: pyre doesn't understand this import
from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from imbue_core.errors import ImbueError
from imbue_core.fixed_traceback import FixedTraceback
from imbue_core.frozen_utils import FrozenDict
from imbue_core.frozen_utils import FrozenMapping
from imbue_core.serialization import SerializedException
from imbue_core.serialization_types import Serializable

T = TypeVar("T")
TYPE_KEY = "__type"
EXCEPTION_KEY = "__exception"

# LABELS for marking attributes with special handling
DONT_SERIALIZE_METADATA_KEY = "_imbue_dont_serialize"
DONT_SERIALIZE = {DONT_SERIALIZE_METADATA_KEY: True}
SERIALIZE_WITH_DEFAULT_KEY = "_imbue_serialize_with_default"
SERIALIZE_WITH_DEFAULT = {SERIALIZE_WITH_DEFAULT_KEY: True}

SERIALIZABLE_PROPERTY_KEY = "_imbue_is_serializable_property"
CACHED_SERIALIZABLE_PROPERTY_KEY = "_imbue_is_cached_serializable_property"


##########################################################################################
# UTILITY FUNCTIONS
##########################################################################################


def _safe_issubclass(t1: type, t2: type) -> bool:
    return inspect.isclass(t1) and issubclass(t1, t2)


def _is_frozen_mapping_type(t: type) -> bool:
    return _safe_issubclass(get_origin(t) or t, FrozenMapping)


def _is_mapping_type(t: type) -> bool:
    return _safe_issubclass(get_origin(t) or t, Mapping)


_ALLOWED_SPECIAL_MAPPING_TYPES = (LRUCache,)


def _is_special_mapping_type(t: type) -> bool:
    return t in _ALLOWED_SPECIAL_MAPPING_TYPES


def _is_str_type_special_mapping_type(t: str) -> bool:
    return t in [_type_to_string(t, fully_qualified=True) for t in _ALLOWED_SPECIAL_MAPPING_TYPES]


def _is_obj_supported_primitive(obj: Any) -> bool:
    return type(obj) in {bool, int, float, str, NoneType}


def _type_to_string(t: type, fully_qualified: bool) -> str:
    name = t.__name__
    if fully_qualified:
        return f"{t.__module__}.{name}"
    else:
        return name


def _type_from_string(type_str: str) -> Any:
    if "[" in type_str:
        class_details, _ = type_str.split("[", 1)
    else:
        class_details = type_str
    if "." in class_details:
        module_path, class_name = class_details.rsplit(".", 1)
        module = importlib.import_module(module_path)
    else:
        class_name = class_details
        module = builtins
    result = getattr(module, class_name)
    return result


def get_serializable_properties(obj: Any) -> dict[str, Any]:
    members = inspect.getmembers(type(obj))
    marked_members = {}
    for name, member in members:
        if is_serializable_property(member):
            marked_members[name] = getattr(obj, name)
    return marked_members


def is_serializable_property(func: Callable) -> bool:
    return getattr(func, CACHED_SERIALIZABLE_PROPERTY_KEY, False) or (
        isinstance(func, property) and getattr(func.fget, SERIALIZABLE_PROPERTY_KEY, False)
    )


def cached_serializable_property(func: Callable[..., T]) -> cached_property[T]:
    property_to_return = cached_property(func)
    setattr(property_to_return, CACHED_SERIALIZABLE_PROPERTY_KEY, True)
    return property_to_return


def serializable_property(func: Callable[..., T]) -> property:
    property_to_return = func
    # NOTE: this will be stored in the fget attribute of the property, which is also the function
    #   we are decorating, so we must check in `func.fget` to see if the property is serializable.
    #   We need to do it this way because we cannot set the attribute on the property object/wrapper
    #   itself, because of the way the inbuilt `property` decorator works.
    setattr(property_to_return, SERIALIZABLE_PROPERTY_KEY, True)
    return property(property_to_return)


def get_dont_serialize_member_names_of_type(obj_type: type) -> list[str]:
    if not attr.has(obj_type):
        return []
    return [field.name for field in attr.fields(obj_type) if field.metadata.get(DONT_SERIALIZE_METADATA_KEY, False)]


def get_serialize_with_default_member_names_of_type(
    obj_type: type,
) -> Mapping[str, Any]:
    if _safe_issubclass(obj_type, BaseModel):
        model_fields = getattr(obj_type, "model_fields", {})
        return {
            name: None if field.default == PydanticUndefined else field.default for name, field in model_fields.items()
        }
    if not attr.has(obj_type):
        return {}
    return {
        field.name: None if field.default == attr.NOTHING else field.default
        for field in attr.fields(obj_type)
        if field.metadata.get(SERIALIZE_WITH_DEFAULT_KEY, False)
    }


def get_dont_serialize_member_names(obj: Any) -> list[str]:
    if not attr.has(obj):
        return []
    members = inspect.getmembers(obj)
    marked_members = []
    for name, _ in members:
        if is_dont_serialize_member(obj, name):
            marked_members.append(name)
    return marked_members


def is_dont_serialize_member(obj: Any, member_name: str) -> bool:
    if not attr.has(obj):
        return False
    for field in attr.fields(obj.__class__):  # type: ignore
        if field.name == member_name:
            return bool(field.metadata.get(DONT_SERIALIZE_METADATA_KEY, False))
    return False


class SerializationError(ImbueError):
    """Raised when we encounter problems related to Serialization or Deserialization."""


def _to_json_dumpable_object_without_type_keys(data: Any) -> Any:
    if isinstance(data, dict):
        if data.get(TYPE_KEY, "") in {
            _type_to_string(PosixPath, fully_qualified=True),
            _type_to_string(Path, fully_qualified=True),
            _type_to_string(UUID, fully_qualified=True),
        }:
            return data["value"]
        else:
            return {
                key: _to_json_dumpable_object_without_type_keys(value) for key, value in data.items() if key != TYPE_KEY
            }
    elif isinstance(data, list):
        return [_to_json_dumpable_object_without_type_keys(item) for item in data]
    elif _is_obj_supported_primitive(data):
        return data
    else:
        return str(data)


def _camelize_keys_which_represent_python_names(data: Any) -> Any:
    """Converts JSON-style objects to use camel case keys.

    Takes a JSON-style object produced by CONVERTER.structure and returns the same object with certain
    keys converted to camel case. Camel cases keys which are derived from names of Python attributes and properties.
    Does not camel-case keys which were keys of dictionaries before serialization.

    See cattrs_serialization_test.test_camel_casing for an example.
    """
    if isinstance(data, dict):
        if TYPE_KEY not in data or issubclass(_type_from_string(data[TYPE_KEY]), Mapping):
            return {key: _camelize_keys_which_represent_python_names(value) for key, value in data.items()}
        else:
            # pyre-ignore[16]: pyre doesn't understand the import of camelize
            return {camelize(key): _camelize_keys_which_represent_python_names(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [_camelize_keys_which_represent_python_names(item) for item in data]
    else:
        return data


##########################################################################################
# CLASS-SPECIFIC HOOKS
##########################################################################################


class _ShouldDeserialize:
    pass


# FIXME: Types such as LRUCache will always serialize without errors since they inherit from Mapping but will not deserialize correctly.
#  We should either document this behavior or change it so that the serialization fails if the type is not supported.
def _serialize_mapping_to_json_dict(data: Mapping, converter: Converter) -> Any:
    assert _is_mapping_type(type(data)), f"Attempted to serialize object of type {type(data)} as a mapping."
    return {str(converter.unstructure(k)): converter.unstructure(v) for k, v in data.items()}


def _serialize_mapping(data: Mapping, converter: Converter) -> Any:
    assert _is_mapping_type(type(data)), f"Attempted to serialize object of type {type(data)} as a mapping."
    entries = [(converter.unstructure(k), converter.unstructure(v)) for k, v in data.items()]
    return {
        TYPE_KEY: _type_to_string(type(data), fully_qualified=True),
        "__entries": entries,
    }


def _deserialize_special_mapping_types(data: dict, type_key: str) -> Mapping:
    if type_key == _type_to_string(LRUCache, fully_qualified=True):
        # FIXME: We're not serializing the object correctly and so the deserialization is hacky
        obj: LRUCache = LRUCache(maxsize=10000)
        return obj
    else:
        raise ValueError(f"Unsupported type {type_key}")


def _deserialize_mapping(data: dict, mapping_type: type, converter: Converter) -> Mapping:
    if TYPE_KEY in data and _is_str_type_special_mapping_type(data[TYPE_KEY]):
        return _deserialize_special_mapping_types(data, data[TYPE_KEY])

    out = {}
    if "__entries" in data:
        entries = data["__entries"]
    else:
        # We keep this branch for backwards compatibility with mappings serialized as dictionaries.
        # We do not support Yasoo's DictWithSerializedKeys -- those will need to be migrated to the new format.
        if TYPE_KEY in data:
            del data[TYPE_KEY]
        entries = data.items()

    for k, v in entries:
        out[converter.structure(k, _ShouldDeserialize)] = converter.structure(v, _ShouldDeserialize)

    if _is_frozen_mapping_type(mapping_type):
        return FrozenDict(out)
    return out


def _serialize_frozen_set(data: frozenset, converter: Converter) -> dict:
    assert type(data) is frozenset, f"Attempted to serialize object of type {type(data)} as a frozenset."
    value = converter.unstructure(data, unstructure_as=list)
    return {"value": value, TYPE_KEY: _type_to_string(type(data), fully_qualified=True)}


def _deserialize_frozen_set(data: dict, _: type, converter: Converter) -> frozenset:
    return frozenset(converter.structure(data["value"], list))


def _serialize_uuid(data: UUID) -> dict:
    if type(data) is UUID:
        return {
            "value": data.hex,
            TYPE_KEY: _type_to_string(type(data), fully_qualified=True),
        }
    elif type(data) is str:
        return {"value": data, TYPE_KEY: _type_to_string(UUID, fully_qualified=True)}
    else:
        raise TypeError("Tried to serialize " + str(data) + ", which is neither a string nor a UUID, as a UUID.")


def _deserialize_uuid(data: dict[str, str] | str, _: type) -> UUID:
    if isinstance(data, dict):
        return UUID(data["value"])
    elif isinstance(data, str):
        return UUID(data)
    else:
        raise TypeError("Tried to deserialize something which is neither a string nor a dictionary, as a UUID.")


def _serialize_tuple(data: tuple, converter: Converter) -> dict:
    assert type(data) is tuple, f"Attempted to serialize object of type {type(data)} as a tuple."
    return {
        "value": [converter.unstructure(x) for x in data],
        TYPE_KEY: _type_to_string(type(data), fully_qualified=True),
    }


def _deserialize_tuple(data: dict, _: type, converter: Converter) -> tuple:
    return tuple(converter.structure(x, _ShouldDeserialize) for x in data["value"])


def _serialize_url(data: URL) -> dict:
    assert type(data) is URL, f"Tried to serialize {data} which is not a URL."
    return {
        "value": str(data),
        TYPE_KEY: _type_to_string(type(data), fully_qualified=True),
    }


def _deserialize_url(data: dict, _: type) -> URL:
    return URL(data["value"])


def _serialize_decimal(data: Decimal) -> dict:
    assert type(data) is Decimal, f"Attempted to serialize object of type {type(data)} as a Decimal."
    return {
        "value": str(data),
        TYPE_KEY: _type_to_string(type(data), fully_qualified=True),
    }


def _deserialize_decimal(data: dict, _: type) -> Decimal:
    return Decimal(data["value"])


def _serialize_traceback(data: FixedTraceback) -> dict:
    assert _safe_issubclass(
        type(data), FixedTraceback
    ), f"Attempted to serialize object of type {type(data)} as a traceback."
    return {
        "value": data.to_dict(),
        TYPE_KEY: _type_to_string(type(data), fully_qualified=True),
    }


def _deserialize_traceback(data: dict, _: type) -> FixedTraceback:
    return FixedTraceback.from_dict(data["value"])


def _serialize_path(data: Path) -> dict:
    assert _safe_issubclass(type(data), Path), f"Attempted to serialize an object of type {type(data)} as a Path."
    return {
        "value": str(data),
        TYPE_KEY: _type_to_string(type(data), fully_qualified=True),
    }


def _deserialize_path(data: Any, _: type) -> Path:
    if type(data) is dict:
        return Path(data["value"])
    return Path(data)


def _serialize_anyio_path(data: anyio.Path) -> dict:
    assert _safe_issubclass(type(data), anyio.Path), f"Attempted to serialize an object of type {type(data)} as a Path."
    return {
        "value": str(data),
        TYPE_KEY: _type_to_string(type(data), fully_qualified=True),
    }


def _deserialize_anyio_path(data: Any, _: type) -> anyio.Path:
    if type(data) is dict:
        return anyio.Path(data["value"])
    return anyio.Path(data)


def _serialize_datetime(data: datetime.datetime) -> dict:
    assert _safe_issubclass(
        type(data), datetime.datetime
    ), f"Attempted to serialize object of type {type(data)} as a datetime."
    return {
        TYPE_KEY: _type_to_string(type(data), fully_qualified=True),
        "time": data.astimezone(datetime.timezone.utc).timestamp(),
        "tzaware": data.tzinfo is not None,
    }


def _deserialize_datetime(data: dict, _: type) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(data["time"], datetime.timezone.utc if data.get("tzaware", None) else None)


def _serialize_bytes(data: bytes) -> dict:
    assert type(data) is bytes, f"Attempted to serialize object of type {type(data)} as bytes."
    return {
        TYPE_KEY: _type_to_string(type(data), fully_qualified=True),
        # use ascii since base64 guarantees ascii characters only
        "value": base64.b64encode(data).decode("ascii"),
    }


def _deserialize_bytes(data: dict, _: type) -> bytes:
    return base64.b64decode(data["value"])


def _is_forward_ref(t: type) -> bool:
    return isinstance(t, ForwardRef)


def _serialize_forward_ref(data: Any, converter: Converter) -> Any:
    return converter.unstructure(data, unstructure_as=type(data))


def _deserialize_forward_ref(data: Any, _: type, converter: Converter) -> Any:
    # TODO: think of a way to evaluate the ForwardRef _, to improve type safety.
    #  Once we do that, we can swap out the evaluated type for ShouldDeserialize
    #  and enforce that we're getting an object of the correct type.
    return _deserialize_serialized_object(data, _ShouldDeserialize, converter)


def _is_union_type(t: type) -> bool:
    origin = get_origin(t)
    return origin is Union or origin is UnionType


def _deserialize_union_type(data: Any, type_of_data: type, converter: Converter) -> Any:
    return converter.structure(data, _ShouldDeserialize)


def _serialize_enum(data: Enum, converter: Converter) -> Any:
    assert inspect.isclass(type(data)) and issubclass(
        type(data), Enum
    ), f"Attempted to serialize object of type {type(data)} as an Enum."
    return converter._unstructure_enum(data)


def _deserialize_enum(data: dict[str, str] | str, t: type) -> Any:
    # We include this complicated logic to preserve backwards compatibility with old JSON that was
    # serialized by Yasoo. Yasoo serialized enums by converting them into the form
    # {"__type": "...", "value": "..."}. Strangely, Yasoo converted this dictionary into a string
    # whenever an enum value occurred as a dictionary key, but did not convert it into a string
    # when it occurred anywhere else. Hence we need to handle enums that are represented by
    # dictionaries, stringified dictionaries, and strings.

    assert _safe_issubclass(t, Enum)

    if isinstance(data, str):
        try:
            # This is the case where data is an enum value, serialized by Cattrs.
            return t(data)
        except ValueError:
            # This is the case where data is a stringified dictionary, serialized by Yasoo.
            data_as_dict = json.loads(data)
            return t[data_as_dict["value"]]  # type: ignore
    else:
        # This is the case where data is a dictionary, serialized by Yasoo.
        return t[data["value"]]  # type: ignore


##########################################################################################
# TYPE KEY LOGIC
##########################################################################################


class _AvoidTypeKeyLogic:
    pass


@lru_cache
def flag_to_ignore_type_key_hooks(t: type) -> type:
    class GivenTypeFlaggedToAvoidTypeKeyLogic(t, _AvoidTypeKeyLogic):
        pass

    GivenTypeFlaggedToAvoidTypeKeyLogic.__name__ = t.__name__
    GivenTypeFlaggedToAvoidTypeKeyLogic.__qualname__ = t.__qualname__

    # pyre-fixme[16]: pyre doesn't understand dynamically created classes
    return GivenTypeFlaggedToAvoidTypeKeyLogic


def get_pydantic_model_attributes(model: BaseModel) -> dict[str, Any]:
    # This is a hack to dump only the top level but also avoid dumping any properties
    attributes = getattr(type(model), "model_fields", {})
    return {a: getattr(model, a) for a in attributes}


# These two factory functions produce the functions for serializing attr classes.
# Only one of them should be registered at a time, depending on whether we are including
# do-not-serialize fields in the serialization.
def _serialize_attr_class_factory(cls: type, converter: Converter) -> Callable[[Any], Any]:
    return make_dict_unstructure_fn(cls, converter)


def _serialize_attr_class_without_dont_serialize_fields(
    cls: type, converter: Converter, is_camel_case: bool
) -> Callable[[Any], Any]:
    members_to_omit = get_dont_serialize_member_names_of_type(cls)
    omit_kwargs = {name: override(omit=True) for name in members_to_omit}
    return make_dict_unstructure_fn(cls, converter, **omit_kwargs)  # type: ignore


def _serialize_with_type_key(data: Any, converter: Converter, for_javascript: bool = False) -> Any:
    type_of_data = type(data)

    if _is_obj_supported_primitive(data) or isinstance(data, list) or isinstance(data, tuple):
        # This means that data was annotated as a Serializable, but it is a primitive or a tuple.
        return converter.unstructure(data, unstructure_as=type_of_data)

    type_of_data_with_typekey_already_added = flag_to_ignore_type_key_hooks(type_of_data)  # type: ignore

    # This is a hack which is necessary because cattrs does not work well with Protocols.
    # Protocols are generic classes, but they don't have __orig_bases__, which cattrs
    # assumes them to have.
    if is_generic(type_of_data_with_typekey_already_added):
        old_orig_bases = getattr(type_of_data_with_typekey_already_added, "__orig_bases__", ())
        setattr(type_of_data_with_typekey_already_added, "__orig_bases__", old_orig_bases)

    if isinstance(data, BaseModel):
        # This is a shortcut: when you encounter a Pydantic model, just use Pydantic serialization.
        # NOTE: currently we don't support `DONT_SERIALIZE` fields in pydantic models.
        #  so we just serialize all fields.
        unstructured = data.model_dump(by_alias=for_javascript, mode="json")
    else:
        unstructured = converter.unstructure(data, unstructure_as=type_of_data_with_typekey_already_added)

    assert isinstance(unstructured, dict)

    if for_javascript:
        unstructured.update({k: converter.unstructure(v) for k, v in get_serializable_properties(data).items()})

    return {
        TYPE_KEY: _type_to_string(type_of_data, fully_qualified=True),
        **unstructured,
    }


# This is the predicate used in the factory functions above, so they trigger for serializable and attr classes
# that have had their type key logic handled.
def _should_serialize_without_type_key(t: type) -> bool:
    is_serializable_class = _safe_issubclass(t, Serializable) or attr.has(t) or _safe_issubclass(t, BaseModel)
    return is_serializable_class and _safe_issubclass(t, _AvoidTypeKeyLogic)


def _should_add_type_key(t: type) -> bool:
    is_serializable_class = _safe_issubclass(t, Serializable) or attr.has(t) or _safe_issubclass(t, BaseModel)
    return is_serializable_class and not _safe_issubclass(t, _AvoidTypeKeyLogic)


def _deserialize_serialized_object(data: Any, type_of_data: type, converter: Converter) -> Any:
    if isinstance(data, list):
        # Data is a list of objects.
        return converter.structure(data, list[_ShouldDeserialize])
    elif not isinstance(data, Mapping):
        # Data is a primitive, like an integer or a string.
        return converter.structure(data, type(data))
    else:
        # Data is a dictionary with a type key, representing an attrs object, a Pydantic model, or a Mapping
        return _deserialize_using_type_marker(data, type_of_data, converter)


def _should_deserialize_with_type_key_logic(t: type) -> bool:
    is_type_that_should_be_deserialized = (
        attr.has(t)
        or _safe_issubclass(t, Serializable)
        or _safe_issubclass(t, _ShouldDeserialize)
        or t is Hashable
        or _is_mapping_type(t)
        or _safe_issubclass(t, BaseModel)
    )
    should_avoid_type_key_logic = _safe_issubclass(t, _AvoidTypeKeyLogic) or _safe_issubclass(
        get_origin(t) or NoneType, _AvoidTypeKeyLogic
    )
    return is_type_that_should_be_deserialized and not should_avoid_type_key_logic


def deserialized_object_violates_target_type(obj: Any, target_type: type) -> bool:
    if target_type is _ShouldDeserialize or target_type is Serializable:
        return False
    if type(target_type) is TypeVar:
        # We're not really able to check if the object is an instance of a type that's behind a TypeVar.
        return False
    return not isinstance(obj, get_origin(target_type) or target_type)


# Note that expected_type_based_on_annotations may be much more vague than the actual type of the object.
# For example: it may be Serializable, when the object is supposed to be
# deserialized as a HammerResult. We get the real type from the "__type" key.
def _deserialize_using_type_marker(
    obj: Mapping[Any, Any],
    expected_type_based_on_annotations: type[T],
    converter: Converter,
) -> T:
    if TYPE_KEY in obj:
        type_of_obj = _type_from_string(obj[TYPE_KEY])
    else:
        type_of_obj = expected_type_based_on_annotations

    if _is_special_mapping_type(type_of_obj):
        pass
    elif _is_frozen_mapping_type(type_of_obj):
        obj.pop(TYPE_KEY, None)  # type: ignore
        type_of_obj = FrozenMapping[_ShouldDeserialize, _ShouldDeserialize]
    elif _is_mapping_type(type_of_obj):
        obj.pop(TYPE_KEY, None)  # type: ignore
        type_of_obj = dict[_ShouldDeserialize, _ShouldDeserialize]
    elif _safe_issubclass(type_of_obj, BaseModel):
        assert isinstance(obj, dict)
        obj.pop(TYPE_KEY, None)
        return cast(T, type_of_obj.model_validate(obj))
    elif not attr.has(type_of_obj):
        # This happens when there is a primitive object which is annotated as Serializable.
        return converter.structure(obj, type_of_obj)  # type: ignore

    # By mixing in the "avoid type key logic" class, force cattrs to do its normal behavior.
    ret: T = converter.structure(obj, flag_to_ignore_type_key_hooks(type_of_obj))

    if inspect.isclass(type_of_obj):
        # Upcast the result so that it has the correct type again, without the mixin.
        object.__setattr__(ret, "__class__", type_of_obj)

    if deserialized_object_violates_target_type(ret, expected_type_based_on_annotations):
        raise TypeError(
            f"Tried to deserialize into type {expected_type_based_on_annotations}, but got object of type {type(ret)}"
        )

    return ret


def _resolve_default(default: Any) -> Any:
    if isinstance(default, attr.Factory):  # type: ignore
        return default.factory()
    return default


def _serialize_with_defaults(cls: type, converter: Converter) -> Callable[[Any], Any]:
    # Handle a pydantic model
    if _safe_issubclass(cls, BaseModel):
        return lambda x: {k: converter.unstructure(v) for k, v in get_pydantic_model_attributes(x).items()}

    members_with_defaults = get_serialize_with_default_member_names_of_type(cls)
    overriden_kwargs = {
        name: override(unstruct_hook=(lambda _, value=_resolve_default(default): value))  # type: ignore
        for name, default in members_with_defaults.items()
    }
    return make_dict_unstructure_fn(cls, converter, **overriden_kwargs)  # type: ignore


def _should_serialize_as_serialized_exception(t: type) -> bool:
    return (
        _safe_issubclass(get_origin(t) or t, BaseException) and not attr.has(t) and not _safe_issubclass(t, BaseModel)
    )


##########################################################################################
# CONVERTER FACTORY
##########################################################################################


class _ConverterFactory:
    """Factory for creating converters with different configurations.

    e.g. for serializing to javascript, or python, or to include do-not-serialize fields.
    """

    def build_base_converter(self) -> Converter:
        # Builds of new base converter object, which registers all the hooks that are common to all converters.
        # The idea being that all new converters start from this base and then override hooks they need to change
        # NOTE: we need to generate a new converter object for each independent concrete converter (as opposed to
        # using converter.copy()) since we use partial functions/closures and this way we ensure the function is
        # being called with the correct converter object.
        converter = Converter()

        converter.register_structure_hook_func(_is_mapping_type, partial(_deserialize_mapping, converter=converter))
        # serialization of mapping types depends on the specific converter so is done in the get_converter factory method

        converter.register_unstructure_hook(frozenset, partial(_serialize_frozen_set, converter=converter))
        converter.register_structure_hook(frozenset, partial(_deserialize_frozen_set, converter=converter))

        converter.register_unstructure_hook(UUID, _serialize_uuid)
        converter.register_structure_hook(UUID, _deserialize_uuid)

        converter.register_unstructure_hook(URL, _serialize_url)
        converter.register_structure_hook(URL, _deserialize_url)

        converter.register_unstructure_hook(Decimal, _serialize_decimal)
        converter.register_structure_hook(Decimal, _deserialize_decimal)

        converter.register_unstructure_hook(FixedTraceback, _serialize_traceback)
        converter.register_structure_hook(FixedTraceback, _deserialize_traceback)

        converter.register_unstructure_hook(Path, _serialize_path)
        converter.register_structure_hook(Path, _deserialize_path)

        converter.register_unstructure_hook(anyio.Path, _serialize_anyio_path)
        converter.register_structure_hook(anyio.Path, _deserialize_anyio_path)

        converter.register_unstructure_hook(datetime.datetime, _serialize_datetime)
        converter.register_structure_hook(datetime.datetime, _deserialize_datetime)

        converter.register_unstructure_hook(bytes, _serialize_bytes)
        converter.register_structure_hook(bytes, _deserialize_bytes)

        converter.register_unstructure_hook(PosixPath, _serialize_path)
        converter.register_structure_hook(PosixPath, _deserialize_path)

        converter.register_unstructure_hook_func(_is_forward_ref, partial(_serialize_forward_ref, converter=converter))
        converter.register_structure_hook_func(_is_forward_ref, partial(_deserialize_forward_ref, converter=converter))

        converter.register_structure_hook_func(_is_union_type, partial(_deserialize_union_type, converter=converter))

        converter.register_structure_hook(NoneType, lambda data, _: None)

        converter.register_unstructure_hook(Enum, partial(_serialize_enum, converter=converter))
        converter.register_structure_hook(Enum, _deserialize_enum)

        converter.register_unstructure_hook_func(
            _should_serialize_as_serialized_exception,
            lambda e: serialize_to_dict(
                SerializedException.build(e),
                use_defaults_for_unserializable_fields=True,
            ),
        )

        converter.register_structure_hook_func(
            _should_deserialize_with_type_key_logic,
            partial(_deserialize_serialized_object, converter=converter),
        )

        converter.register_structure_hook_func(
            lambda t: isinstance(t, TypeVar),
            partial(_deserialize_serialized_object, converter=converter),
        )

        return converter

    def get_converter_with_defaults(self, converter: Converter) -> Converter:
        converter.register_unstructure_hook(asyncio.Lock, lambda _: None)
        converter.register_structure_hook(asyncio.Lock, lambda data, _: asyncio.Lock())

        converter.register_unstructure_hook(asyncio.Task, lambda _: None)
        converter.register_structure_hook(asyncio.Task, lambda data, _: None)

        converter.register_unstructure_hook(asyncio.Queue, lambda _: None)
        converter.register_structure_hook(asyncio.Queue, lambda data, _: None)

        converter.register_unstructure_hook(asyncio.Event, lambda _: None)
        converter.register_structure_hook(asyncio.Event, lambda data, _: None)

        converter.register_unstructure_hook(asyncio.Semaphore, lambda _: None)
        converter.register_structure_hook(asyncio.Semaphore, lambda data, _: None)

        converter.register_unstructure_hook(abc.ABCMeta, lambda _: None)
        converter.register_structure_hook(abc.ABCMeta, lambda data, _: None)
        converter.register_unstructure_hook_factory(
            _should_serialize_without_type_key,
            partial(_serialize_with_defaults, converter=converter),
        )

        return converter

    @functools.cache
    def get_converter(
        self,
        for_javascript: bool = False,
        exclude_dont_serialize_fields: bool = False,
        use_defaults_for_unserializable_fields: bool = False,
    ) -> Converter:
        """Returns a converter with the given configuration.

        The result of this method is cached, so subsequent calls with the same arguments will return the same converter.
        """
        assert not (
            exclude_dont_serialize_fields and use_defaults_for_unserializable_fields
        ), f"Expected exactly one flag to be set, got {exclude_dont_serialize_fields=}, {use_defaults_for_unserializable_fields=}"

        converter = self.build_base_converter()
        if for_javascript:
            converter.register_unstructure_hook_func(
                _is_mapping_type,
                partial(_serialize_mapping_to_json_dict, converter=converter),
            )
        else:
            converter.register_unstructure_hook_func(_is_mapping_type, partial(_serialize_mapping, converter=converter))
            converter.register_unstructure_hook(tuple, partial(_serialize_tuple, converter=converter))
            converter.register_structure_hook(tuple, partial(_deserialize_tuple, converter=converter))

        if exclude_dont_serialize_fields:
            converter.register_unstructure_hook_factory(
                _should_serialize_without_type_key,
                partial(
                    _serialize_attr_class_without_dont_serialize_fields,
                    converter=converter,
                    is_camel_case=for_javascript,
                ),
            )
        else:
            converter.register_unstructure_hook_factory(
                _should_serialize_without_type_key,
                partial(_serialize_attr_class_factory, converter=converter),
            )
        if use_defaults_for_unserializable_fields:
            converter = self.get_converter_with_defaults(converter)

        converter.register_unstructure_hook_func(
            _should_add_type_key,
            partial(
                _serialize_with_type_key,
                converter=converter,
                for_javascript=for_javascript,
            ),
        )

        return converter


CONVERTER_FACTORY = _ConverterFactory()


##########################################################################################
# ENTRY POINTS
##########################################################################################


def _serialize_to_json_dumpable_object(
    obj: Any,
    is_reversible: bool = True,
    for_javascript: bool = False,
    exclude_dont_serialize_fields: bool = False,
    use_defaults_for_unserializable_fields: bool = False,
) -> Any:
    if exclude_dont_serialize_fields:
        # Check and raise error to make it clear to the caller that the object cannot be deserialized.
        # This is a sanity check, to make it easier to debug when using do-not-serialize fields.
        # NOTE: this will only catch cases where non-serializable fields are in obj, but not cases where
        # the non-serializable fields are in nested objects, checking for the nested case is a little complicated
        # so we don't do it basically.
        assert (
            not is_reversible
        ), "Cannot deserialize object when excluding do-not-serialize fields (i.e. when `exclude_dont_serialize_fields=True`). If you want to serialize an object and exclude do-not-serialize fields, make sure to set `is_reversible=False`."

    if use_defaults_for_unserializable_fields:
        # The point of the use_defaults_for_unserializable_fields flag is to make it possible to serialize objects
        # and then recreate them later even if certain fields are not fully saved. We never want to use this flag
        # with `is_reversible=False` since we won't know the type to be able to recreate the object.
        assert is_reversible, "Cannot restructure inputs if is_reversible=False"

    # TODO: this is a hack to make it possible to serialize ExecutionContexts for class methods.
    #  This lets us serialize ExecutionContexts for calls to class methods without serializing the class itself.
    #  The long-term solution is to write a custom hook that can serialize type objects.
    if type(obj) is dict and "__class__" in obj:
        del obj["__class__"]

    converter = CONVERTER_FACTORY.get_converter(
        for_javascript=for_javascript,
        exclude_dont_serialize_fields=exclude_dont_serialize_fields,
        use_defaults_for_unserializable_fields=use_defaults_for_unserializable_fields,
    )

    dict_result = converter.unstructure(obj)
    if for_javascript:
        dict_result = _camelize_keys_which_represent_python_names(dict_result)

    if not is_reversible:
        return _to_json_dumpable_object_without_type_keys(dict_result)

    return dict_result


def serialize_to_dict(
    obj: Any,
    is_reversible: bool = True,
    for_javascript: bool = False,
    exclude_dont_serialize_fields: bool = False,
    use_defaults_for_unserializable_fields: bool = False,
) -> dict[str, Any]:
    """Serialize to a python dict."""
    return cast(
        dict[str, Any],
        _serialize_to_json_dumpable_object(
            obj,
            is_reversible=is_reversible,
            for_javascript=for_javascript,
            exclude_dont_serialize_fields=exclude_dont_serialize_fields,
            use_defaults_for_unserializable_fields=use_defaults_for_unserializable_fields,
        ),
    )


def serialize_to_json(
    obj: Any,
    indent: int | None = None,
    sort_keys: bool = False,
    is_reversible: bool = True,
    for_javascript: bool = False,
    exclude_dont_serialize_fields: bool = False,
    use_defaults_for_unserializable_fields: bool = False,
) -> str:
    """Serialize an object to a JSON string.

    This is the main serialization entrypoint.

    `is_reversible` controls whether we enforce that the result can be deserialized. In some cases we don't care about
    reversibility, e.g. when serializing data for a frontend we often don't care whether we can deserialize.

    `for_javascript` controls whether we use camelCase for keys that originally were Python identifiers.

    `exclude_dont_serialize_fields` controls whether we include do-not-serialize fields in the serialization.
    If this is `False` then any attr class fields marked with as don't serialize, e.g. with `attr.ib(metadata=DONT_SERIALIZE)`,
    will still be included in the serialization. If this is `True` then they will be excluded, however this also means that
    the result will not be reversible (and thus the caller will have to set `is_reversible=False`).

    `use_defaults_for_unserializable_fields` controls whether we fill fields that cannot be serialized with their default values.
    IMPORTANT: If you use this flag, data may be discarded during deserialization.
    The goal is to be able to deserialize fields to the original type without caring about the data contained.
    Default value choices (guided by crafty serialization requirements):
    - Fields that are marked with attr.ib(metadata=SERIALIZE_WITH_DEFAULT) have the following default values:
        - Fields that are marked with `attr.ib(default=...)` or `attr.ib(factory=...)` use their default values.
        - Fields that do not have a default value are filled with None.
    - Asyncio objects are filled with None.
    - Exceptions are replaced with a string representation
    """
    try:
        unstructured = _serialize_to_json_dumpable_object(
            obj,
            is_reversible=is_reversible,
            for_javascript=for_javascript,
            exclude_dont_serialize_fields=exclude_dont_serialize_fields,
            use_defaults_for_unserializable_fields=use_defaults_for_unserializable_fields,
        )
        return json.dumps(unstructured, indent=indent, sort_keys=sort_keys)
    except Exception as e:
        raise SerializationError(str(e)) from e


def deserialize_from_json(
    data: str,
    for_javascript: bool = False,
    exclude_dont_serialize_fields: bool = False,
    use_defaults_for_unserializable_fields: bool = False,
) -> Any:
    try:
        converter = CONVERTER_FACTORY.get_converter(
            for_javascript=for_javascript,
            exclude_dont_serialize_fields=exclude_dont_serialize_fields,
            use_defaults_for_unserializable_fields=use_defaults_for_unserializable_fields,
        )
        return _deserialize_serialized_object(json.loads(data), _ShouldDeserialize, converter=converter)
    except Exception as e:
        raise SerializationError(str(e)) from e


def deserialize_from_dict(
    data: dict[str, Any],
    as_type: type = _ShouldDeserialize,
    for_javascript: bool = False,
    exclude_dont_serialize_fields: bool = False,
    use_defaults_for_unserializable_fields: bool = False,
) -> Any:
    try:
        converter = CONVERTER_FACTORY.get_converter(
            for_javascript=for_javascript,
            exclude_dont_serialize_fields=exclude_dont_serialize_fields,
            use_defaults_for_unserializable_fields=use_defaults_for_unserializable_fields,
        )
        return _deserialize_using_type_marker(data, as_type, converter=converter)
    except Exception as e:
        raise SerializationError(str(e)) from e


def deserialize_from_dict_with_type(data: dict[str, Any], obj_type: type[T]) -> T:
    try:
        converter = CONVERTER_FACTORY.get_converter(for_javascript=False, exclude_dont_serialize_fields=False)
        result = converter.structure(data, obj_type)
        assert isinstance(result, obj_type), f"Expected an object of type {obj_type}, but got {result}"
        return result
    except Exception as e:
        raise SerializationError(str(e)) from e


def deserialize_from_json_with_type(data: str | bytes | bytearray, obj_type: type[T]) -> T:
    try:
        converter = CONVERTER_FACTORY.get_converter(for_javascript=False, exclude_dont_serialize_fields=False)
        return cast(
            T,
            _deserialize_serialized_object(json.loads(data), obj_type, converter=converter),
        )
    except Exception as e:
        raise SerializationError(str(e)) from e
