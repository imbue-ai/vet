import asyncio
import functools
import threading
from typing import Awaitable
from typing import Callable
from typing import ParamSpec
from typing import TypeVar

P = ParamSpec("P")
R = TypeVar("R")


def sync(func: Callable[P, Awaitable[R]]) -> Callable[P, R]:
    """Decorator that runs an async function synchronously by dispatching to
    an event loop running in a separate thread.
    """

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        loop = _get_or_create_event_loop()
        return asyncio.run_coroutine_threadsafe(func(*args, **kwargs), loop).result()

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
        threading.Thread(target=_LOOP.run_forever, daemon=True, name="async_loop").start()
    return _LOOP  # pyre-ignore[7]: we just made _LOOP, so it's not None unless it got destroyed just now


def make_async(func: Callable[P, R]) -> Callable[P, Awaitable[R]]:
    """
    Turn the annotated function into an async function by running it in a thread.

    This is useful for functions that perform blocking i/o.
    """

    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        return await asyncio.to_thread(func, *args, **kwargs)

    return wrapper
