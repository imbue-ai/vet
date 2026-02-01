import asyncio
import functools
import inspect
import threading
import traceback
from contextlib import AbstractAsyncContextManager
from contextlib import AbstractContextManager
from contextlib import contextmanager
from pathlib import Path
from types import FrameType
from typing import Any
from typing import AsyncGenerator
from typing import Awaitable
from typing import Callable
from typing import Coroutine
from typing import Generator
from typing import ParamSpec
from typing import TypeVar

P = ParamSpec("P")
R = TypeVar("R")
S = TypeVar("S")


def sync(func: Callable[P, Awaitable[R]]) -> Callable[P, R]:
    """Decorator that runs an async function synchronously by dispatching to
    an event loop running in a separate thread.
    """

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        loop = _get_or_create_event_loop()
        return asyncio.run_coroutine_threadsafe(func(*args, **kwargs), loop).result()

    return wrapper


def sync_generator(
    func: Callable[P, AsyncGenerator[R, None]],
) -> Callable[P, Generator[R, None, None]]:
    """Decorator that runs an async generator synchronously by dispatching to
    an event loop running in a separate thread.
    """

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> Generator[R, None, None]:
        loop = _get_or_create_event_loop()
        agen = func(*args, **kwargs)
        while True:
            try:
                future = asyncio.run_coroutine_threadsafe(agen.__anext__(), loop)
                yield future.result()
            except StopAsyncIteration:
                break

    return wrapper


@contextmanager
# pyre-ignore[24]: pyre doesn't understand AbstractAsyncContextManager
def sync_contextmanager(
    async_context_manager: AbstractAsyncContextManager[S],
) -> Generator[S, None, None]:
    sync_aenter = sync(async_context_manager.__aenter__)
    sync_aexit = sync(async_context_manager.__aexit__)

    enter_result = sync_aenter()
    try:
        yield enter_result
    except BaseException as e:
        if not sync_aexit(e.__class__, e, e.__traceback__):
            raise
    else:
        sync_aexit(None, None, None)


# pyre doesn't understand AbstractAsyncContextManager
def sync_contextmanager_func(
    cm_func: Callable[P, AbstractAsyncContextManager[S]],  # pyre-ignore[24]
) -> Callable[P, AbstractContextManager[S]]:  # pyre-ignore[24]
    @functools.wraps(cm_func)
    def wrapper(
        *args: P.args, **kwargs: P.kwargs
    ) -> AbstractContextManager[S]:  # pyre-ignore[24]
        return sync_contextmanager(cm_func(*args, **kwargs))

    return wrapper


_LOOP: asyncio.AbstractEventLoop | None = None
_LOOP_LOCK: threading.Lock = threading.Lock()


def _get_or_create_event_loop() -> asyncio.AbstractEventLoop:
    global _LOOP
    if _LOOP is not None:
        return _LOOP
    with _LOOP_LOCK:
        # Check again in case another thread created the loop while we were waiting for the lock.
        if _LOOP is not None:
            return _LOOP
        _LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_LOOP)
        # pyre-ignore[16]: we have _LOOP_LOCK, so _LOOP is still not None
        threading.Thread(
            target=_LOOP.run_forever, daemon=True, name="async_loop"
        ).start()
    return _LOOP  # pyre-ignore[7]: we just made _LOOP, so it's not None unless it got destroyed just now


def shorten_filename(filename: str) -> str:
    path = Path(filename)
    while path.parent:
        path = path.parent
        if not (path / "__init__.py").exists():
            break

    try:
        shortened = str(Path(filename).relative_to(path))
    except ValueError:
        shortened = filename  # in case the path cannot be made relative

    return shortened


def extract_frames(task: asyncio.Task) -> list[FrameType]:
    """Extract the stack frames of an async task."""
    coro = task.get_coro()
    assert isinstance(coro, Coroutine)
    frames = []
    while coro is not None and coro.cr_frame is not None:
        frames.append(coro.cr_frame)
        coro = coro.cr_await  # type: ignore
        # this happens at the very bottom of the call stack, there it seems to often be a FutureIter, Event, etc
        if type(coro).__name__ != "coroutine":
            break
    return frames


def make_async(func: Callable[P, R]) -> Callable[P, Awaitable[R]]:
    """
    Turn the annotated function into an async function by running it in a thread.

    This is useful for functions that perform blocking i/o.
    """

    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        return await asyncio.to_thread(func, *args, **kwargs)

    return wrapper
