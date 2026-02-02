import builtins
import datetime
import json
from enum import Enum
from functools import cached_property
from importlib import import_module
from importlib.metadata import version
from pathlib import PosixPath
from traceback import format_tb
from types import TracebackType
from typing import Any
from typing import Hashable
from typing import Iterable
from typing import Mapping
from typing import TypeVar
from typing import cast
from uuid import UUID

from loguru import logger
from typing_extensions import TypeAliasType
from yasoo import Deserializer
from yasoo import Serializer
from yasoo.constants import ENUM_VALUE_KEY
from yasoo.objects import DictWithSerializedKeys
from yasoo.serialization import _convert_to_json_serializable
from yasoo.utils import get_fields
from yasoo.utils import is_obj_supported_primitive
from yasoo.utils import normalize_type
from yasoo.utils import resolve_types

from vet.imbue_core.fixed_traceback import FixedTraceback
from vet.imbue_core.pydantic_serialization import SerializableModel
from vet.imbue_core.serialization_types import Serializable

assert (
    version("yasoo") == "0.12.6"
), "This code was written for yasoo 0.12.6 and requires inheriting / monkeypatching the deserializer, so you probably don't want to use any other version without fixing TupleDeserializer"

T = TypeVar("T", bound=Hashable)


class TupleDeserializer(Deserializer):
    def _deserialize(
        self,
        data: bool | int | float | str | list[Any] | dict[str, Any] | None,
        obj_type: type[T] | None,
        type_key: str | None,
        allow_extra_fields: bool,
        external_globals: dict[str, Any],
        ignore_custom_deserializer: bool = False,
    ) -> object:
        all_globals = dict(globals())
        all_globals.update(external_globals)
        if is_obj_supported_primitive(data):
            return data
        if isinstance(data, list):
            list_types = self._get_list_types(obj_type, data)
            return tuple([self._deserialize(d, t, type_key, allow_extra_fields, all_globals) for t, d in list_types])

        assert isinstance(data, dict), f"Expected a dict, but got {type(data)}"

        # load wrapped primitives
        if type_key is not None:
            type_data = data.get(type_key, None)

            if type_data is not None and type_data.startswith("builtins.") and type_data != "builtins.dict":
                return data["value"]

        # TODO: we need to potentially handle `builtins.dict`
        # if type_key is not None:
        #     type_data = data.get(type_key, None)
        #
        #     # TODO: serialization currently breaks with builtin.dicts and dicts with non-string keys
        #     if type_data == "builtins.dict":
        #         raise NotImplementedError(
        #             "Only `FrozenMapping` is supported for dict serialization/deserialization, call `freeze_mapping` on your dict before serializing"
        #         )
        #     if type_data is not None and type_data.startswith("builtins.") and type_data != "builtins.dict":
        #         return data["value"]

        # TODO: remove this hack. Many of our sqlite files (search s3_sqlite_path) have FrozenDicts
        if isinstance(type_key, str) and data.get(type_key, None) == "flax.core.frozen_dict.FrozenDict":
            data[type_key] = "imbue_core.frozen_utils.FrozenMapping"
        # we deliberately pass in a `None` type_key sometimes, which results in just returning obj_type
        obj_type = self._get_object_type(obj_type, data, type_key, all_globals)  # pyre-ignore[6]
        if type_key in data:
            data.pop(type_key)
        real_type, generic_args = normalize_type(obj_type, all_globals)
        if external_globals and isinstance(real_type, type):
            bases = {real_type}
            while bases:
                all_globals.update((b.__name__, b) for b in bases)
                bases = {ancestor for b in bases for ancestor in b.__bases__}

        if not ignore_custom_deserializer:
            deserialization_method = self._custom_deserializers.get(obj_type, self._custom_deserializers.get(real_type))
            if deserialization_method:
                return deserialization_method(data)
            for base_class, method in self._inheritance_deserializers.items():
                if issubclass(real_type, base_class):
                    return method(data, real_type)

        key_type = None
        try:
            # pyre-fixme[6]: obj_type needs to be Hashable, but pyre isn't sure that it is
            fields = {f.name: f for f in get_fields(obj_type)}
        except TypeError:
            if obj_type is FixedTraceback:
                return FixedTraceback.from_dict(data["value"])
            if issubclass(real_type, Enum):
                value = data[ENUM_VALUE_KEY]
                if isinstance(value, str):
                    try:
                        return real_type[value]
                    except KeyError:
                        for e in real_type:
                            if e.name.lower() == value.lower():
                                return e
                return real_type(value)
            # TODO: serialization currently breaks with builtin.dicts and dicts with non-string keys
            #   if you have weird keys in your dict this branch won't be hit and your object won't be properly deserialized
            elif issubclass(real_type, Mapping):
                key_type = generic_args[0] if generic_args else None
                if self._is_mapping_dict_with_serialized_keys(key_type, data):
                    # pyre-fixme[9]: obj_type needs to be Hashable, but pyre doesn't realize that type[DictWithSerializedKeys] is ok
                    obj_type = DictWithSerializedKeys
                    # pyre-fixme[6]: arg of get_fields needs to be Hashable, but pyre doesn't realize that type[DictWithSerializedKeys] is ok
                    fields = {f.name: f for f in get_fields(DictWithSerializedKeys)}
                    value_type = generic_args[1] if generic_args else Any
                    fields["data"].field_type = dict[str, value_type]  # type: ignore
                else:
                    return self._load_mapping(
                        data,
                        real_type,
                        generic_args,
                        type_key,
                        allow_extra_fields,
                        all_globals,
                    )
            elif issubclass(real_type, Iterable):
                # If we got here it means data is not a list, so obj_type came from the data itself and is safe to use
                return self._load_iterable(data, obj_type, type_key, allow_extra_fields, all_globals)
            elif real_type != obj_type:
                return self._deserialize(data, real_type, type_key, allow_extra_fields, external_globals)
            else:
                raise

        self._check_for_missing_fields(data, fields, obj_type)
        self._check_for_extraneous_fields(data, fields, obj_type, allow_extra_fields)
        self._load_inner_fields(data, fields, type_key, allow_extra_fields, all_globals)
        if obj_type is DictWithSerializedKeys:
            return self._load_dict_with_serialized_keys(
                obj_type(**data), key_type, type_key, allow_extra_fields, all_globals
            )
        kwargs = {k: v for k, v in data.items() if fields[k].init}
        assert obj_type is not None
        result = obj_type(**kwargs)
        for k, v in data.items():
            if k not in kwargs:
                setattr(result, k, v)
        return result


# TODO: probably a good idea to ensure that all dicts are frozen as well...
class FrozenSerializer(Serializer):
    def __init__(self, force_serialization: bool, allow_unsafe_list_serialization: bool = False) -> None:
        super().__init__()
        self._force_serialization = force_serialization
        self._allow_unsafe_list_serialization = allow_unsafe_list_serialization

    def _serialize_iterable(
        self,
        obj: Iterable[object],
        type_key: Any,
        fully_qualified_types: Any,
        preserve_iterable_types: Any,
        stringify_dict_keys: Any,
    ) -> list[object]:
        if isinstance(obj, list):
            if self._allow_unsafe_list_serialization:
                logger.info("Converting list to tuple for serialization: {}", obj)
                obj = tuple(obj)
            else:
                raise Exception(f"Lists are not allowed for serialization. Use tuples instead. Current iterable: {obj}")
        assert isinstance(
            obj, (tuple, frozenset, bytes)
        ), f"All iterables should be tuples or frozenset. Received {obj}"
        return cast(
            list[object],
            tuple(
                self._serialize(
                    item,
                    type_key,
                    fully_qualified_types,
                    preserve_iterable_types,
                    stringify_dict_keys,
                )
                for item in obj
            ),
        )

    # overriding this method just to get some better error messages out--previously it would just "type error" and
    # moan about things like int64 not being serializable, which is fine, but it is nicer if the key is included
    def serialize(
        self,
        obj: Any,
        type_key: str | None = "__type",
        fully_qualified_types: bool = True,
        preserve_iterable_types: bool = False,
        stringify_dict_keys: bool = True,
        globals: dict[str, Any] | None = None,
    ) -> bool | int | float | str | list | dict[str, Any] | None:
        try:
            if is_obj_supported_primitive(obj):
                return obj  # type: ignore

            if globals:
                self._custom_serializers = resolve_types(self._custom_serializers, globals)  # type: ignore

            result = self._serialize(
                obj,
                type_key,
                fully_qualified_types,
                preserve_iterable_types,
                stringify_dict_keys,
                inner=False,
            )
            try:
                result = _convert_to_json_serializable(result)
            except TypeError:
                _convert_to_json_serializable_with_better_errors(result)
                assert False, "previous method should have raised..."
            return result  # type: ignore
        except Exception:
            if self._force_serialization:
                return repr(obj)
            else:
                raise


JsonTypeAlias = TypeAliasType(
    "JsonTypeAlias",
    "dict[str, JsonTypeAlias] | list[JsonTypeAlias] | str | int | float | bool | None",
)


class SerializedException(SerializableModel):
    """A serializable dataclass that represents an exception"""

    exception: str
    args: "tuple[SerializedException | JsonTypeAlias, ...]"  # pyre-ignore[11]: pyre doesn't like TypeAliasType
    traceback_dict: JsonTypeAlias

    @classmethod
    def build(cls, exception: BaseException, traceback: TracebackType | None = None) -> "SerializedException":
        if traceback is None:
            traceback = exception.__traceback__
            assert traceback is not None, " ".join(
                (
                    "No traceback deriveable or as a concrete argument!",
                    f"You probably want to convert_to_serialized_exception in your except clause: {exception=}",
                )
            )
        return SerializedException(  # pyre-fixme[28]: pyre doesn't understand pydantic
            exception=get_fully_qualified_name_for_error(exception),
            args=tuple(_convert_serialized_exception_args(x, traceback) for x in exception.args),
            traceback_dict=FixedTraceback.from_tb(traceback).as_dict(),
        )


def _convert_serialized_exception_args(error: Serializable, traceback: TracebackType | None = None) -> JsonTypeAlias:
    if isinstance(error, BaseException):
        return SerializedException.build(error, traceback=traceback)
    elif isinstance(error, (list, tuple)):
        return tuple(_convert_serialized_exception_args(x, traceback) for x in error)
    return error


def get_fully_qualified_name_for_error(e: BaseException) -> str:
    if e.__class__.__module__ == "builtins":
        return e.__class__.__name__
    return f"{e.__class__.__module__}.{e.__class__.__name__}"


def _convert_to_json_serializable_with_better_errors(
    obj: Any, path: str = ""
) -> int | float | str | list | dict | None:
    if is_obj_supported_primitive(obj):
        return obj  # type: ignore
    if isinstance(obj, Mapping):
        return {
            key: _convert_to_json_serializable_with_better_errors(value, f"{path}.{key}") for key, value in obj.items()
        }
    if isinstance(obj, Iterable):
        return [_convert_to_json_serializable_with_better_errors(item, f"{path}[{i}]") for i, item in enumerate(obj)]
    raise TypeError(f'Found object of type "{type(obj).__name__}" at {path} which cannot be serialized')


SERIALIZER = FrozenSerializer(force_serialization=False, allow_unsafe_list_serialization=False)
DESERIALIZER = TupleDeserializer()

# note: you cannot change this without changing other calls to yasoo, this is its default
TYPE_KEY = "__type"


class SerializationError(Exception):
    pass


@SERIALIZER.register()
def serialize_frozen_set(data: frozenset) -> dict:
    value = SERIALIZER.serialize(tuple(data))
    return {"value": value}


@DESERIALIZER.register()
def deserialize_frozen_set(data: dict) -> frozenset:
    return frozenset(DESERIALIZER.deserialize(data["value"], tuple))


@SERIALIZER.register()
def serialize_uuid(data: UUID) -> dict:
    return {"value": data.hex}


@DESERIALIZER.register()
def deserialize_uuid(data: dict) -> UUID:
    return UUID(data["value"])


@SERIALIZER.register()
def serialize_traceback(data: FixedTraceback) -> dict:
    return {"value": data.to_dict()}


@DESERIALIZER.register()
def deserialize_traceback(data: dict) -> FixedTraceback:
    return FixedTraceback.from_dict(data["value"])


@SERIALIZER.register()
def serialize_posix_path(data: PosixPath) -> dict:
    return {"value": str(data)}


@DESERIALIZER.register()
def deserialize_posix_path(data: dict) -> PosixPath:
    return PosixPath(data["value"])


@SERIALIZER.register()
def serialize_datetime(data: datetime.datetime) -> dict:
    return {
        "time": data.astimezone(datetime.timezone.utc).timestamp(),
        "tzaware": data.tzinfo is not None,
        "__type": "datetime.datetime",
    }


@DESERIALIZER.register()
def deserialize_datetime(data: dict) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(data["time"], datetime.timezone.utc if data.get("tzaware", None) else None)


def serialize_to_json(obj: Any, indent: int | None = None, sort_keys: bool = False) -> str:
    try:
        return json.dumps(SERIALIZER.serialize(obj), indent=indent, sort_keys=sort_keys)
    except Exception as e:
        raise SerializationError(str(e)) from e


def deserialize_from_json(data: str) -> Any:
    try:
        return DESERIALIZER.deserialize(json.loads(data))  # pyre-ignore[20]: pyre doesn't understand deserialize
    except Exception as e:
        raise SerializationError(str(e)) from e
