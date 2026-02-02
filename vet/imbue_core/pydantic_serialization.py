import threading
from typing import Any
from typing import TypeVar
from typing import cast

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Discriminator
from pydantic.alias_generators import to_camel

from vet.imbue_core.nested_evolver import _Evolver
from vet.imbue_core.nested_evolver import chill
from vet.imbue_core.nested_evolver import evolver
from vet.imbue_core.serialization_types import Serializable

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
