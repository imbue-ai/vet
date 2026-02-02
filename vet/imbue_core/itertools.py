import contextlib
import itertools
from typing import Generator
from typing import Iterable
from typing import Sequence
from typing import TypeVar

from vet.imbue_core.errors import ImbueError

T = TypeVar("T")


class ImbueItertoolsValueError(ImbueError, ValueError):
    """This value error is thrown when the assumptions of the itertools module are violated."""


def flatten(iterable: Iterable[Iterable[T]]) -> list[T]:
    return list(itertools.chain.from_iterable(iterable))


def remove_none(data: Iterable[T | None]) -> list[T]:
    return [x for x in data if x is not None]


def only(x: Iterable[T]) -> T:
    try:
        (value,) = x
    except ValueError as e:
        message = "Expected exactly one value"
        if isinstance(x, Sequence):
            with contextlib.suppress():
                message += f" but got {len(x)} {x[:3]=}"
        raise ImbueItertoolsValueError(message) from e

    return value


def first(iterable: Iterable[T]) -> T | None:
    return next(iter(iterable), None)


# TODO replace with itertools.batched when we can require Python 3.12+
def generate_chunks(iterable: Iterable[T], chunk_size: int) -> Generator[tuple[T, ...], None, None]:
    """Yield successive n-sized chunks from any iterable"""
    chunk = []
    for item in iterable:
        chunk.append(item)
        if len(chunk) == chunk_size:
            yield tuple(chunk)
            chunk = []
    if len(chunk) > 0:
        yield tuple(chunk)
