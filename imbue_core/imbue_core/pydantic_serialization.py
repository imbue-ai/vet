import threading
from typing import Any
from typing import TypeVar
from typing import cast
from typing import get_args

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Discriminator
from pydantic import GetCoreSchemaHandler
from pydantic import Json
from pydantic.alias_generators import to_camel
from pydantic_core import core_schema as pyd_core_schema

from imbue_core.frozen_utils import FrozenDict
from imbue_core.nested_evolver import _Evolver
from imbue_core.nested_evolver import chill
from imbue_core.nested_evolver import evolver
from imbue_core.serialization_types import Serializable

T = TypeVar("T", bound=BaseModel)
V = TypeVar("V")

_threading_local = threading.local()


class EvolvableModel:
    # pyre-ignore[47]: pyre is not so easily tricked
    def evolve(self: T, attribute: V, new_value: V) -> T:
        # pyre-ignore[16]: pyre doesn't know about evolved_obj
        assert _threading_local.evolved_obj is not None, ".ref() must be called before evolve"

        assert isinstance(attribute, _Evolver)  # Tricked you, type system!
        dest_evolver: _Evolver[T] = cast(_Evolver[T], attribute)
        dest_evolver.assign(new_value)

        result = chill(_threading_local.evolved_obj)
        _threading_local.evolved_obj = None
        return result

    # pyre-ignore[47]: pyre is not so easily tricked
    def ref(self: T) -> T:
        # pyre-ignore[16]: pyre doesn't know about evolved_obj
        _threading_local.evolved_obj = evolver(self)
        return _threading_local.evolved_obj


class FrozenModel(EvolvableModel, BaseModel):
    """
    The base class for most internal data (that does not need to be serialized).

    We generally prefer to keep data immutable in order to avoid side effects, race conditions, etc
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        arbitrary_types_allowed=False,
    )


class MutableModel(BaseModel):
    """
    The base class for any internal data that strictly must be mutable.  Should be used sparingly.
    """

    model_config = ConfigDict(
        frozen=False,
        extra="forbid",
        # FIXME: go back to preventing arbitrary types once we're done converting
        # arbitrary_types_allowed=False,
        arbitrary_types_allowed=True,
    )


class SerializableModel(EvolvableModel, BaseModel, Serializable):
    """
    The base class for all data that can be serialized to/from JSON.
    """

    model_config = ConfigDict(
        frozen=True,
        ser_json_bytes="base64",
        val_json_bytes="base64",
        alias_generator=to_camel,
        validate_by_alias=True,
        validate_by_name=True,
        # any extra values will end up in the __pydantic_extra__ field
        # this is effectively required for backwards compatibility
        # IMPORTANT: note that, by default, we clear this below!  These types are ONLY for backwards compatibility
        extra="allow",
        # this is also effectively required for backwards compatibility
        arbitrary_types_allowed=True,
    )

    # this is a place where we might way to do any backwards compatibility related logic
    def model_post_init(self, __context: Any) -> None:
        pydantic_extra = self.__pydantic_extra__
        assert pydantic_extra is not None
        pydantic_extra.clear()


def model_dump(obj: BaseModel, is_camel_case: bool = False) -> dict:
    return obj.model_dump(by_alias=is_camel_case)


def model_load(model_type: type[T], data: dict) -> T:
    return model_type.model_validate(data)


def model_dump_json(obj: BaseModel | Json, is_camel_case: bool = False) -> str:
    # pyre-fixme[16]: pyre complains that obj can be pydantic.types.AnyType, which has no model_dump_json
    return obj.model_dump_json(by_alias=is_camel_case)


def model_load_json(model_type: type[T], data: str) -> T:
    return model_type.model_validate_json(data)


# this is mostly here for the default cases.
# When you want to upgrade a model (and keep it backwards compatible), you can make a custom discriminator
# (eg, that looks for the old type name or converts the old class names)
def build_discriminator(
    field_name: str = "object_type",
    additional_types_and_string_representations: tuple[tuple[type, str], ...] = (),
) -> Discriminator:
    """
    Build a discriminator function for a Pydantic model.

    Args:
        field_name (str): The name of the field to use as the discriminator.
        additional_types_and_string_representations (Tuple[Tuple[Type, str], ...]): Register additional types to the discriminator.

    Returns:
        Callable[[T | dict], str]: A function that takes an instance of T or a dictionary and returns the value of the
            specified field.
    """

    def discriminator(obj: T | dict) -> str:
        for (
            model_type,
            string_representation,
        ) in additional_types_and_string_representations:
            if isinstance(obj, model_type):
                return string_representation
        if isinstance(obj, dict):
            if field_name not in obj:
                return obj[to_camel(field_name)]
            return obj[field_name]
        return getattr(obj, field_name)

    return Discriminator(discriminator=discriminator)


class PydanticFrozenDictAnnotation:
    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> pyd_core_schema.CoreSchema:
        def validate_from_dict(d: dict | FrozenDict) -> FrozenDict:
            return FrozenDict(d)

        frozendict_schema = pyd_core_schema.chain_schema(
            [
                # pyre-ignore[16]: pyre is confused by using dict as a type like this
                handler.generate_schema(dict[*get_args(source_type)]),
                pyd_core_schema.no_info_plain_validator_function(validate_from_dict),
                pyd_core_schema.is_instance_schema(FrozenDict),
            ]
        )
        return pyd_core_schema.json_or_python_schema(
            json_schema=frozendict_schema,
            python_schema=frozendict_schema,
            serialization=pyd_core_schema.plain_serializer_function_ser_schema(dict),
        )
