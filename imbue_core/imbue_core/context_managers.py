from contextlib import contextmanager
from typing import Callable
from typing import Generator


@contextmanager
def call_on_exit(callback: Callable[[BaseException | None], None]) -> Generator[None, None, None]:
    """
    A context manager that calls a given callback function upon exiting the context.

    The callback function receives an exception instance if an exception was raised, None otherwise.

    """
    try:
        yield
    except BaseException as e:
        try:
            callback(e)
        finally:
            raise
    else:
        callback(None)
