"""Evolver uses duck-typing to give the appearance of editing a frozen, nested structure of attrs classes and tuples, recording changes in a way that they can be applied to generate a newly frozen instance.

One of the design goals is that mypy, autocomplete, and automatic refactoring work for the assignments made into these nested structures.

See: https://imbue-ai.slack.com/archives/C05D0SM2RT5/p1726185313480779?thread_ts=1722865932.537289&cid=C05D0SM2RT5

If you make changes here and then the tests fail with:
```
E   RecursionError: maximum recursion depth exceeded
!!! Recursion detected (same locals & position)
```
It's possible that you're accidentally invoking `Evolver.something_undefined` and that's causing the infinite recursion.
Mypy cannot catch this when it thinks the type is an `Evolver` because the `Evolver` class has a `__getattr__` method that makes it look like any attribute access could be valid.
"""

import threading
from typing import Any
from typing import Callable
from typing import Generic
from typing import TypeGuard
from typing import TypeVar
from typing import cast

import attr
from pydantic import BaseModel

from imbue_core.frozen_utils import FrozenDict
from imbue_core.pydantic_utils import model_update

_T = TypeVar("_T")
ObjectType = TypeVar("ObjectType")


def evolver(obj: _T) -> _T:
    """Creates a wrapper around an immutable attrs object, tuple, or FrozenDict that records potentially nested attribute assignments.

    The return type is our first white lie to the type system.
    """
    result = _Evolver[_T](obj)
    # The cast is a little white lie to the type system to make type-checking, autocomplete, and refactoring work.
    return cast(_T, result)


def assign(dest: _T, src: Callable[[], _T]) -> None:
    """Since mypy would complain about assignments to frozen attrs fields, use this function to make assignments.

    The only reason src is a `Callable[[], _T]` instead of just `_T` is that it makes type checking signal attempts to assign
    the wrong type to the field.  Surprisingly, just using `(dest: _T, src: _T)` doesn't cause mypy to complain about type mismatch.
    """
    assert isinstance(dest, _Evolver)  # Tricked you, type system!
    dest_evolver: _Evolver[_T] = cast(_Evolver[_T], dest)
    dest_evolver.assign(src())


def chill(evolver: _T) -> _T:
    """Produces a new frozen instance with the recorded changes applied.

    The name `chill` is a play on the fact that original input was frozen, and we are now re-freezing it.
    """
    assert isinstance(evolver, _Evolver)  # Tricked you, type system!
    cast_evolver = cast(_Evolver[_T], evolver)
    return cast_evolver.chill()


_threading_local = threading.local()


# TODO: since mutate and thaw are stateful, if you call one without the other, you run into problems.
def thaw(obj: _T) -> _T:
    global _threading_local
    if hasattr(_threading_local, "evolved_obj"):
        raise ValueError("Thaw does not support nested thawing.")
    # pyre-ignore[16]: we're deliberately setting evolved_obj for the first time here
    _threading_local.evolved_obj = evolver(obj)
    return _threading_local.evolved_obj


# TODO: mypy complains because the input isn't anything related to ObjectType, but the output is.
# This also means the type checking doesn't quite work since it can't infer the return type of this function correctly
def mutate(dest: _T, src: Callable[[], _T]) -> ObjectType:  # type: ignore
    assign(dest, src)
    try:
        # pyre-ignore[34]: we don't have generic functions yet, so pyre complains that ObjectType isn't in the input
        evolved_obj: ObjectType = _threading_local.evolved_obj  # pyre-ignore[16]: pyre doesn't know about evolved_obj
        return chill(evolved_obj)
    except AttributeError as e:
        raise ValueError("You must call mutate on a thawed object") from e
    finally:
        delattr(_threading_local, "evolved_obj")


def mutate_from_dict(dest: ObjectType, src: dict[str, Any]) -> ObjectType:
    # Warning: using this function doesn't provide mypy type checking at the call site, but it allows a single interface for attrs and pydantic classes
    # In most cases the above function should be used instead
    evolved_obj = evolver(dest)
    for key, value in src.items():
        assign(getattr(evolved_obj, key), lambda: value)
    return chill(evolved_obj)


def evolver_isinstance(evolver: Any, cls: type[_T]) -> TypeGuard[_T]:
    assert isinstance(evolver, _Evolver)  # Tricked you, type system!
    return evolver.isinstance(cls)


class _RegularValue:
    regular_value: Any

    def __init__(self, value: Any) -> None:
        self.regular_value = value


class _AttrValue:
    attr_value: Any
    child_evolver_by_name: dict[str, "_Evolver[Any]"]

    def __init__(self, value: Any) -> None:
        self.attr_value = value
        self.child_evolver_by_name = {}


class _PydanticModelValue:
    pydantic_model_value: Any
    child_evolver_by_name: dict[str, "_Evolver[Any]"]

    def __init__(self, value: Any) -> None:
        self.pydantic_model_value = value
        self.child_evolver_by_name = {}


class _TupleValue:
    tuple_evolvers: list["_Evolver[Any]"]

    def __init__(self, value: tuple[Any, ...]) -> None:
        # It may be premature to create evolvers for all the elements of the tuple, but it's easier.
        self.tuple_evolvers = [evolver(item) for item in value]


class _FrozenDictValue:
    frozen_dict_evolvers: dict[Any, "_Evolver[Any]"]

    def __init__(self, value: dict[Any, Any]) -> None:
        # It may be premature to create evolvers for all the elements of dict, but it's easier.
        self.frozen_dict_evolvers = {k: evolver(v) for k, v in value.items()}


class _Evolver(Generic[_T]):
    # pyre-ignore[13]: pyre is confused by the trickery here
    _value: _RegularValue | _AttrValue | _TupleValue | _FrozenDictValue | _PydanticModelValue

    def __init__(self, initial_value: _T) -> None:
        super().__init__()
        self.assign(initial_value)

    def assign(self, new_value: _T) -> None:
        """Assign a new value to this Evolver, recording a change to the frozen structure to be later applied during `chill()`."""

        if attr.has(type(new_value)):
            self._value = _AttrValue(new_value)
        elif isinstance(new_value, BaseModel):
            self._value = _PydanticModelValue(new_value)
        elif isinstance(new_value, tuple):
            self._value = _TupleValue(new_value)
        elif isinstance(new_value, FrozenDict):
            self._value = _FrozenDictValue(new_value)
        else:
            self._value = _RegularValue(new_value)

    def __getattr__(self, item: str) -> "_Evolver[Any]":
        """Access Evolvers for nested members of a frozen attrs object."""
        try:
            value = self._value
            if isinstance(value, _AttrValue):
                if item not in value.child_evolver_by_name:
                    child_obj = getattr(value.attr_value, item)
                    result = evolver(child_obj)
                    assert isinstance(result, _Evolver), "Expose a lie to the type system."
                    value.child_evolver_by_name[item] = result
                return value.child_evolver_by_name[item]
            elif isinstance(value, _PydanticModelValue):
                if item not in value.child_evolver_by_name:
                    child_obj = getattr(value.pydantic_model_value, item)
                    result = evolver(child_obj)
                    assert isinstance(result, _Evolver), "Expose a lie to the type system."
                    value.child_evolver_by_name[item] = result
                return value.child_evolver_by_name[item]
            raise TypeError(
                f"You're trying to access field {item=} on an object of {type(value)=} that doesn't have that field (should have been a mypy error)."
            )
        except BaseException as e:
            if hasattr(_threading_local, "evolved_obj"):
                # pyre-ignore[16]: pyre is suspicious of the trickery here
                if getattr(_threading_local, "evolved_obj") == self:
                    delattr(_threading_local, "evolved_obj")
            raise e

    # TODO: It wouldn't be terribly difficult to support "appending" to the tuple as well, by appending to this list.
    def __getitem__(self, key: Any) -> "_Evolver[Any]":
        """Access Evolvers for the elements of a tuple or dict."""
        value = self._value
        if isinstance(value, _TupleValue):
            assert isinstance(key, int)
            return value.tuple_evolvers[key]
        elif isinstance(value, _FrozenDictValue):
            if key not in value.frozen_dict_evolvers:
                # Presumably we're going to evolver_assign to this very soon.
                cast(_FrozenDictValue, self._value).frozen_dict_evolvers[key] = _Evolver(_RegularValue(None))
            return cast(_FrozenDictValue, self._value).frozen_dict_evolvers[key]
        raise TypeError(
            f"You're using [square_brackets] access {key=} on an object of {type(self._value)=} that doesn't support this (should have been a mypy error)."
        )

    def chill(self) -> _T:
        """Recursively apply the recorded changes to the original object and return a new frozen instance."""
        if isinstance(self._value, _AttrValue):
            new_children: dict[str, Any] = {
                name: chill(child) for name, child in self._value.child_evolver_by_name.items()
            }
            assert attr.has(self._value.attr_value.__class__)
            return cast(_T, attr.evolve(cast(Any, cast(_AttrValue, self._value).attr_value), **new_children))
        elif isinstance(self._value, _PydanticModelValue):
            return cast(
                _T,
                model_update(
                    self._value.pydantic_model_value,
                    update={name: chill(child) for name, child in self._value.child_evolver_by_name.items()},
                ),
            )
        elif isinstance(self._value, _TupleValue):
            return cast(_T, tuple(evolver.chill() for evolver in self._value.tuple_evolvers))
        elif isinstance(self._value, _RegularValue):
            return cast(_T, self._value.regular_value)
        elif isinstance(self._value, _FrozenDictValue):
            return cast(_T, FrozenDict({k: v.chill() for k, v in self._value.frozen_dict_evolvers.items()}))
        raise ValueError(f"This Evolver has no value to evolve, {type(self._value)=}.")

    def isinstance(self, cls: type[_T]) -> bool:
        """Check if the object being evolved is an instance of the given class."""
        if isinstance(self._value, _AttrValue):
            return isinstance(self._value.attr_value, cls)
        elif isinstance(self._value, _PydanticModelValue):
            return isinstance(self._value.pydantic_model_value, cls)
        elif isinstance(self._value, _FrozenDictValue):
            return cls == FrozenDict
        return False
