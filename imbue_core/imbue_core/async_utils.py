import asyncio
import functools
import inspect
import os
import platform
import sys
import threading
import traceback
from contextlib import AbstractAsyncContextManager
from contextlib import AbstractContextManager
from contextlib import contextmanager
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from http.server import HTTPServer
from pathlib import Path
from types import FrameType
from typing import Any
from typing import AsyncGenerator
from typing import Awaitable
from typing import Callable
from typing import Coroutine
from typing import Generator
from typing import Generic
from typing import Iterable
from typing import Iterator
from typing import ParamSpec
from typing import TypeVar
from typing import cast
from urllib.parse import parse_qs
from urllib.parse import urlparse

from loguru import logger
from traceback_with_variables.core import _iter_lines

from imbue_core.async_monkey_patches import log_exception
from imbue_core.async_monkey_patches import safe_cancel

P = ParamSpec("P")
R = TypeVar("R")
S = TypeVar("S")

ALL_EVENT_LOOPS: list[asyncio.AbstractEventLoop] = []


def sync(func: Callable[P, Awaitable[R]]) -> Callable[P, R]:
    """Decorator that runs an async function synchronously by dispatching to
    an event loop running in a separate thread.
    """

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        loop = _get_or_create_event_loop()
        return asyncio.run_coroutine_threadsafe(func(*args, **kwargs), loop).result()

    return wrapper


def sync_generator(func: Callable[P, AsyncGenerator[R, None]]) -> Callable[P, Generator[R, None, None]]:
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
def sync_contextmanager(async_context_manager: AbstractAsyncContextManager[S]) -> Generator[S, None, None]:
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
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> AbstractContextManager[S]:  # pyre-ignore[24]
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
        threading.Thread(target=_LOOP.run_forever, daemon=True, name="async_loop").start()
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


# TODO: I'd really like to print these task groups in a hierarchical way instead of flat -- we know which groups
#  launched which other groups, so we could print them in a tree structure. That would be a lot more readable.
#  It might also be nice to print without any stacks at all. As long as the tasks had good names, that would make it
#  possible to very easily understand everything that was currently executing.
#  I could even imagine controls that allowed for printing just the task groups themselves, which would also be easier
#  to understand.
def get_all_async_task_stacks(
    num_skipped_frames: int = 0, log_variables: bool = False, loop: asyncio.AbstractEventLoop | None = None
) -> Iterator[str]:
    """Yields the lines of a report for all stack frames of all async tasks including variables."""
    tasks_by_task_group: dict[asyncio.TaskGroup | None, list[asyncio.Task]] = {}
    owning_task_by_task_group: dict[asyncio.TaskGroup, asyncio.Task] = {}

    for task in asyncio.all_tasks(loop=loop):
        if task.done():
            continue
        task_group = cast(asyncio.TaskGroup | None, getattr(task, "task_group", None))
        owned_task_group = cast(asyncio.TaskGroup | None, getattr(task, "owned_task_group", None))
        if owned_task_group is not None:
            owning_task_by_task_group[owned_task_group] = task
            if owned_task_group not in tasks_by_task_group:
                tasks_by_task_group[owned_task_group] = []
        else:
            tasks_by_task_group.setdefault(task_group, []).append(task)

    all_owning_tasks = set(owning_task_by_task_group.values())

    task_group_keys = list(tasks_by_task_group.keys())
    for task_group in cast(list[asyncio.TaskGroup | None], [None]) + [x for x in task_group_keys if x is not None]:
        if task_group not in tasks_by_task_group:
            continue
        tasks = tasks_by_task_group[task_group]
        if task_group is None:
            yield f"\n\n{'=' * 40}\nNo TaskGroup:\n"
        else:
            yield f"\n\n{'=' * 40}\nTaskGroup: {getattr(task_group, 'name', 'unknown')}\n"
        owning_task = None
        if task_group is not None:
            owning_task = owning_task_by_task_group.get(task_group)
        is_first_line_skipped = False
        all_tasks = tasks
        if owning_task is not None:
            yield f"Owning Task: {owning_task.get_name()}\n"
            is_first_line_skipped = True
            all_tasks.insert(0, owning_task)
        for task in all_tasks:
            # skip these -- they'll be printed at the top of the group that they own
            if task_group is None and task in all_owning_tasks:
                continue
            if is_first_line_skipped:
                is_first_line_skipped = False
            else:
                yield f"{'-' * 40}\nTask {task.get_name()}:\n"
            frames = extract_frames(task)
            for frame in frames:
                frame_infos = inspect.getouterframes(frame)[num_skipped_frames:]
                # Use private method _iter_lines to traceback async tasks, which is not explicitly handled in the API
                if log_variables:
                    for line in _iter_lines(
                        e=None,
                        frame_infos=frame_infos,
                        fmt=None,
                        for_file=None,
                    ):
                        yield line + "\n"
                else:
                    frame_summaries = [
                        traceback.FrameSummary(
                            shorten_filename(info.filename),
                            lineno=info.lineno,
                            name=info.function,
                            line=info.code_context[0].strip() if info.code_context else None,
                        )
                        for info in frame_infos
                    ]
                    yield from traceback.format_list(frame_summaries)


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


def print_all_async_task_stacks(log_variables: bool = False) -> None:
    """Prints the stack frames of all running tasks."""
    for line in get_all_async_task_stacks(log_variables=log_variables):
        print(line)


def dump_all_async_task_stacks(log_path: str | Path, log_variables: bool = False) -> None:
    """Dump the stack frames of all running tasks to file."""
    with open(log_path, "w") as f:
        for line in get_all_async_task_stacks(log_variables=log_variables):
            if log_variables:
                line += "\n"
            f.write(line)


async def periodically_log_async_stacks(log_dir: str | Path, interval: float, log_variables: bool = False) -> None:
    """Periodically print the stack traces of all running tasks."""
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    while True:
        log_path = Path(log_dir) / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        dump_all_async_task_stacks(log_path=log_path, log_variables=log_variables)
        logger.debug("Dumped asyncio stack traces to {}", log_path)
        await asyncio.sleep(interval)


async def is_task_group_complete(
    task_group: asyncio.TaskGroup, trace_task: asyncio.Task, buffer_time: float = 1.0
) -> None:
    """Continuously check if all tasks except the stack trace logger are done."""
    while True:
        if all(task.done() for task in task_group._tasks if task is not trace_task):
            await asyncio.sleep(buffer_time)  # Wait for buffer time in case new tasks are added
            # Recheck to confirm
            if all(task.done() for task in task_group._tasks if task is not trace_task):
                break
        await asyncio.sleep(1.0)


async def inject_async_stack_trace_logger(
    task_group: asyncio.TaskGroup, log_dir: str | Path, log_interval: float = 60.0, log_variables: bool = False
) -> None:
    """Inject a stack trace logger into the task group."""
    trace_task = asyncio.create_task(
        periodically_log_async_stacks(log_dir=log_dir, interval=log_interval, log_variables=log_variables),
        name="periodically_log_async_stacks",
    )
    await is_task_group_complete(task_group, trace_task)
    safe_cancel(trace_task)
    try:
        await trace_task
    except asyncio.CancelledError:
        pass


class AsyncTaskStacksHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        try:
            parsed_url = urlparse(self.path)
            query_params = parse_qs(parsed_url.query)
            log_variables = query_params.get("locals", ["false"])[0].lower() in ["true", "1", "yes"]

            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()

            pid = os.getpid()
            command_line = " ".join(sys.argv)

            # Path to the Python executable
            python_executable = sys.executable

            # Python version
            python_version = platform.python_version()

            # Print the collected information
            self.wfile.write(f"Process {pid}: {python_executable} {command_line}\n".encode("utf-8"))
            self.wfile.write(f"Python v{python_version} ({python_executable})\n\n".encode("utf-8"))

            for loop in ALL_EVENT_LOOPS:
                for line in get_all_async_task_stacks(log_variables=log_variables, loop=loop):
                    self.wfile.write(line.encode("utf-8"))
        except BaseException as e:
            log_exception(e, "exception in AsyncTaskStacksHandler")
            raise


def run_async_stackframe_server_thread(port_range_low: int, port_range_high: int) -> None:
    try:
        success = False
        for port in range(port_range_low, port_range_high):
            try:
                server_address = ("localhost", port)
                httpd = HTTPServer(server_address, AsyncTaskStacksHandler)
                success = True
                print(f"Starting async stack trace server on port {port}. Process pid: {os.getpid()}")
                break
            except OSError:
                continue

        if not success:
            logger.info("Could not find an open port to start the async stack trace server, continuing without it.")
            return

        httpd.serve_forever()
    except BaseException as e:
        log_exception(e, "exception in run_async_stackframe_server_thread")
        raise


IS_STACKFRAME_SERVER_RUNNING = False
STACKFRAME_SERVER_PORT_LOW = 60000
STACKFRAME_SERVER_PORT_HIGH = 61000


def run_async_stackframe_server_for_loop(event_loop: asyncio.AbstractEventLoop) -> None:
    ALL_EVENT_LOOPS.append(event_loop)
    run_async_stackframe_server()


def run_async_stackframe_server() -> None:
    global IS_STACKFRAME_SERVER_RUNNING
    if not IS_STACKFRAME_SERVER_RUNNING:
        IS_STACKFRAME_SERVER_RUNNING = True

        port_str = os.environ.get("ASYNC_STACKFRAME_SERVER_PORT")
        if port_str is not None:
            try:
                port = int(port_str)
                port_range_low = port
                port_range_high = port + 1
            except ValueError:
                logger.error("ASYNC_STACKFRAME_SERVER_PORT is not an integer: {}", port_str)
                raise
        else:
            port_range_low = STACKFRAME_SERVER_PORT_LOW
            port_range_high = STACKFRAME_SERVER_PORT_HIGH

        thread = threading.Thread(
            target=run_async_stackframe_server_thread,
            daemon=True,
            kwargs={"port_range_low": port_range_low, "port_range_high": port_range_high},
        )
        thread.start()


def with_timeout(func: Callable[P, Awaitable[R]], timeout_secs: float) -> Callable[P, Awaitable[R]]:
    """Decorator that adds a timeout to an async function."""

    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        return await asyncio.wait_for(func(*args, **kwargs), timeout_secs)

    return wrapper


T = TypeVar("T")


async def gather_with_limited_concurrency(coros: Iterable[Awaitable[T]], n: int) -> list[T]:
    """Like asyncio.gather() but will only run `n` in parallel at a time.

    Note that a call like `asyncio.gather(*coros)` is now `gather_with_limited_concurrency(coros, n=10),
    without the splat.
    """
    semaphore = asyncio.Semaphore(n)

    async def sem_coro(coro: Awaitable[T]) -> T:
        async with semaphore:
            return await coro

    return list(await asyncio.gather(*(sem_coro(c) for c in coros)))


_NOT_FOUND = object()


class AsyncCachedProperty(Generic[T]):
    """A descriptor factory that behaves very similarly to `functools.cached_property`, but for
    async methods!

    The type annotations here are rough; it's not realistic to get them perfect without using a .pyi file.
    """

    def __init__(self, func: Callable[[Any], Coroutine[None, None, T]]) -> None:
        self.func = func
        self.attrname: str | None = None
        self.__doc__ = func.__doc__

    def __set_name__(self, owner: type, name: str) -> None:
        if self.attrname is None:
            self.attrname = name
        elif name != self.attrname:
            raise TypeError("Cannot assign the same AsyncCachedProperty to multiple names")

    def _get_attrname(self) -> str:
        if self.attrname is None:
            raise TypeError("Cannot use AsyncCachedProperty instance without calling __set_name__")
        return self.attrname

    def _get_cache(self, instance: object) -> dict[str, Any]:
        try:
            return instance.__dict__
        except AttributeError:
            raise TypeError(
                "Cannot use AsyncCachedProperty with instances that do not have a __dict__ attribute"
            ) from None

    def __get__(self, instance: object, owner: type | None = None) -> Awaitable[T]:
        if instance is None:
            return self  # type: ignore
        attrname = self._get_attrname()
        cache = self._get_cache(instance)
        val = cache.get(attrname, _NOT_FOUND)
        if val is not _NOT_FOUND:
            return cast(Awaitable[T], val)

        task = asyncio.create_task(self.func(instance))
        cache[attrname] = task
        return task

    def __delete__(self, instance: object) -> None:
        if instance is None:
            raise TypeError("Cannot delete AsyncCachedProperty on a class")
        attrname = self._get_attrname()
        cache = self._get_cache(instance)
        try:
            awaitable = cache.pop(attrname)
            if not awaitable.done():
                safe_cancel(awaitable)
        except KeyError:
            raise AttributeError(f"Cannot delete attribute {self.attrname!r}") from None

    def __set__(self, instance: object, value: T) -> None:
        if instance is None:
            raise TypeError("Cannot set AsyncCachedProperty on a class")
        attrname = self._get_attrname()
        cache = self._get_cache(instance)
        existing = cache.pop(attrname, None)
        if existing is not None and not existing.done():
            safe_cancel(existing)
        fut: asyncio.Future[T] = asyncio.Future()
        fut.set_result(value)
        cache[attrname] = fut


def wrapped_asyncio_run(
    main: Awaitable[T],
    *,
    debug: bool | None = None,
    loop_factory: Callable[..., asyncio.AbstractEventLoop] | None = None,
) -> T:
    """
    This is a lightweight wrapper with a singular purpose -- it is here to enable apyspy

    apyspy is our async equivalent to py-spy.

    Without apyspy, it's really annoying to debug why some async task is stuck.
    """

    async def wrapper_main() -> T:
        ALL_EVENT_LOOPS.append(asyncio.get_event_loop())
        result = await main
        ALL_EVENT_LOOPS.pop()
        return result

    run_async_stackframe_server()
    with asyncio.Runner(debug=debug, loop_factory=loop_factory) as runner:
        return runner.run(wrapper_main())


def make_async(func: Callable[P, R]) -> Callable[P, Awaitable[R]]:
    """
    Turn the annotated function into an async function by running it in a thread.

    This is useful for functions that perform blocking i/o.
    """

    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        return await asyncio.to_thread(func, *args, **kwargs)

    return wrapper
