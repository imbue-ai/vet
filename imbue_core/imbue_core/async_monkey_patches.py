import asyncio
import sys
import traceback
from asyncio import Future
from types import TracebackType
from typing import Any
from typing import Sequence

from loguru import logger

from imbue_core.errors import ExpectedError

_IS_SHUTTING_DOWN = False


def notify_task_groups_of_shutdown() -> None:
    global _IS_SHUTTING_DOWN
    _IS_SHUTTING_DOWN = True


class PropagatingTaskGroup(asyncio.TaskGroup):
    """Improves over TaskGroup by ensuring that cancelation messages are actually propagated"""

    def __init__(self) -> None:
        # deferring the import in case this doesn't get used
        pass

        python_version: sys._version_info = sys.version_info
        if python_version[:2] != (3, 11) and python_version[:2] != (3, 12):
            raise RuntimeError(
                f"Python version 3.11 or 3.12 is required. You are using {python_version.major}.{python_version.minor}"
            )
        super().__init__()
        self._entered = False
        self._exiting = False
        self._aborting = False
        self._loop = None
        self._parent_task: asyncio.Task | None = None
        self._parent_cancel_requested = False
        self._tasks: set[asyncio.Task] = set()
        self._errors: list[BaseException] = []
        self._base_error: BaseException | None = None
        self._on_completed_fut: Future[Any] | None = None
        self._original_message: str | None = None

    async def __aexit__(
        self,
        et: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            return await self._aexit(et, exc)
        finally:
            # Exceptions are heavy objects that can have object
            # cycles (bad for GC); let's not keep a reference to
            # a bunch of them. It would be nicer to use a try/finally
            # in __aexit__ directly but that introduced some diff noise
            self._parent_task = None
            self._errors = []  # Clear the list instead of setting to None
            self._base_error = None
            exc = None

    async def _aexit(
        self, et: type[BaseException] | None, exc: BaseException | None
    ) -> None:
        self._exiting = True

        if exc is not None and self._is_base_error(exc) and self._base_error is None:  # type: ignore
            self._base_error = exc

        propagate_cancellation_error = (
            exc if et is asyncio.exceptions.CancelledError else None
        )
        if self._parent_cancel_requested:
            # If this flag is set we *must* call uncancel().
            assert self._parent_task
            if self._parent_task.uncancel() == 0:
                # If there are no pending cancellations left,
                # don't propagate CancelledError.
                propagate_cancellation_error = None

        if et is not None:
            if not self._aborting:
                # Our parent task is being cancelled:
                #
                #    async with TaskGroup() as g:
                #        g.create_task(...)
                #        await ...  # <- CancelledError
                #
                # or there's an exception in "async with":
                #
                #    async with TaskGroup() as g:
                #        g.create_task(...)
                #        1 / 0
                assert exc is not None
                self._abort_and_propagate(exc)

        # We use while-loop here because "self._on_completed_fut"
        # can be cancelled multiple times if our parent task
        # is being cancelled repeatedly (or even once, when
        # our own cancellation is already in progress)
        while self._tasks:
            if self._on_completed_fut is None:
                assert self._loop
                self._on_completed_fut = self._loop.create_future()

            try:
                await self._on_completed_fut
            except asyncio.exceptions.CancelledError as ex:
                if not self._aborting:
                    # Our parent task is being cancelled:
                    #
                    #    async def wrapper():
                    #        async with TaskGroup() as g:
                    #            g.create_task(foo)
                    #
                    # "wrapper" is being cancelled while "foo" is
                    # still running.
                    propagate_cancellation_error = ex
                    self._abort_and_propagate(ex)

            self._on_completed_fut = None

        assert not self._tasks

        if self._base_error is not None:
            try:
                raise self._base_error
            finally:
                exc = None

        # Propagate CancelledError if there is one, except if there
        # are other errors -- those have priority.
        try:
            if propagate_cancellation_error and not self._errors:
                try:
                    raise propagate_cancellation_error
                finally:
                    exc = None
        finally:
            propagate_cancellation_error = None

        if et is not None and et is not asyncio.exceptions.CancelledError:
            assert exc is not None
            self._errors.append(exc)

        if self._errors:
            try:
                raise BaseExceptionGroup(
                    "unhandled errors in a TaskGroup: see earlier in logs for causal error!",
                    self._errors,
                ) from None
            finally:
                exc = None

    def _abort(self) -> None:
        raise Exception("Please call _abort_and_propagate instead")

    def _abort_and_propagate(self, exc: BaseException) -> None:
        global _IS_SHUTTING_DOWN
        self._aborting = True

        if self._original_message is None:
            if isinstance(exc, asyncio.exceptions.CancelledError) and len(exc.args) > 0:
                self._original_message = "TaskGroup canceled because:\n" + exc.args[0]
            else:
                if not isinstance(exc, asyncio.exceptions.CancelledError):
                    if not _IS_SHUTTING_DOWN and not isinstance(exc, ExpectedError):
                        log_exception(
                            exc,
                            "Emergency print of error that caused task group to die:",
                        )
                self._original_message = (
                    f"TaskGroup died because: {type(exc).__name__}: {exc}\n"
                    + "".join(traceback.extract_tb(exc.__traceback__).format())
                )

        for t in self._tasks:
            if not t.done():
                t.cancel(self._original_message)

    def _on_task_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)

        on_completed_fut = self._on_completed_fut
        if on_completed_fut is not None and not self._tasks:
            if not on_completed_fut.done():
                on_completed_fut.set_result(True)

        if task.cancelled():
            return

        exc = task.exception()
        if exc is None:
            return

        self._errors.append(exc)
        if self._is_base_error(exc) and self._base_error is None:  # type: ignore
            self._base_error = exc

        parent_task = self._parent_task
        assert parent_task
        if parent_task.done():
            # Not sure if this case is possible, but we want to handle
            # it anyways.
            assert self._loop
            self._loop.call_exception_handler(
                {
                    "message": f"Task {task!r} has errored out but its parent task {parent_task} is already completed",
                    "exception": exc,
                    "task": task,
                }
            )
            return

        if not self._aborting and not self._parent_cancel_requested:
            # If parent task *is not* being cancelled, it means that we want
            # to manually cancel it to abort whatever is being run right now
            # in the TaskGroup.  But we want to mark parent task as
            # "not cancelled" later in __aexit__.  Example situation that
            # we need to handle:
            #
            #    async def foo():
            #        try:
            #            async with TaskGroup() as g:
            #                g.create_task(crash_soon())
            #                await something  # <- this needs to be canceled
            #                                 #    by the TaskGroup, e.g.
            #                                 #    foo() needs to be cancelled
            #        except Exception:
            #            # Ignore any exceptions raised in the TaskGroup
            #            pass
            #        await something_else     # this line has to be called
            #                                 # after TaskGroup is finished.
            self._abort_and_propagate(exc)
            self._parent_cancel_requested = True
            parent_task.cancel(self._original_message)


def safe_cancel(task: asyncio.Task, msg: str | None = None) -> None:
    """
    NOTE: this is probably not what you want!  See safe_cancel_and_wait_for_cleanup below for the more common use case.

    Cancels a task in a way that preserves information about who canceled it.

    Without using this, it is super obnoxious to figure out why your function is being canceled --
    you just get a CancelledError with no traceback.

    We try to ensure that *all* of our tasks are canceled in this way, which makes debugging much easier.

    Even safe_cancel_and_wait_for_cleanup will cancel in this way. The only difference is that that function
    also waits for the task to actually be canceled. Otherwise, cancellation just enqueues a cancellation.

    Note also that cancellation is never guaranteed -- all it does is raise a CancelledError in the task.
    This is why it is so important to never swallow those errors!
    """
    task.is_being_canceled_by_us = True  # type: ignore
    message = f"Task canceled by: \n {''.join(traceback.format_stack()[:-1])}"
    if msg:
        message += f"\nOriginal message: {msg}"

    task.cancel(message)


async def safe_cancel_and_wait_for_cleanup(
    task: asyncio.Task,
    msg: str | None = None,
    exception_types_to_ignore: Sequence[type[BaseException]] = (),
) -> None:
    """
    Convenience function for calling safe_cancel_multiple_and_wait_for_cleanup with a single task.

    See safe_cancel_multiple_and_wait_for_cleanup for docs.
    """
    await safe_cancel_multiple_and_wait_for_cleanup(
        [task], msg, exception_types_to_ignore
    )


async def safe_cancel_multiple_and_wait_for_cleanup(
    tasks: Sequence[asyncio.Task],
    msg: str | None = None,
    exception_types_to_ignore: Sequence[type[BaseException]] = (),
) -> None:
    """
    Calls safe_cancel (see docs above) on each task in tasks, then waits for them to be done.

    Note that you can pass in a list of exception types to ignore.
    This is important for suppressing exceptions from third party libraries.
    You should probably make a constant in your project that lists these exceptions.

    We cannot simply suppress all BaseExceptions here because you really don't want to do that for things like signals and OutOfMemoryError
    """
    for task in tasks:
        safe_cancel(task, msg)
    # if you really want something to be canceled, you need to wait for it to be done
    # https://docs.python.org/3/library/asyncio-task.html#asyncio.Task.cancel
    results = await asyncio.gather(*tasks, return_exceptions=True)
    exceptions = []
    for result in results:
        if isinstance(result, BaseException):
            if isinstance(result, asyncio.CancelledError):
                pass
            elif isinstance(result, ExceptionGroup):
                exceptions.extend(_filter_exception_group(result))
            else:
                exceptions.append(result)  # type: ignore
        # cannot do this because the task may have just finished
        # assert (
        #     False
        # ), f"While cancelling async task and waiting for cleanup, expected None or CancelledError, got `{type(x)}: {x}`"

    filtered_exceptions = []
    for exception in exceptions:
        if not any(
            isinstance(exception, exception_type)
            for exception_type in exception_types_to_ignore
        ):
            filtered_exceptions.append(exception)

    if len(filtered_exceptions) == 1:
        raise filtered_exceptions[0]
    elif len(filtered_exceptions) > 1:
        raise ExceptionGroup(
            "Multiple exceptions in task group while canceling", filtered_exceptions
        )


def _filter_exception_group(exc_group: ExceptionGroup) -> list[Exception]:
    """Recursively extract exceptions from ExceptionGroups (ignoring canceled errors)."""
    result = []
    for exc in exc_group.exceptions:
        if isinstance(exc, asyncio.CancelledError):
            continue
        elif isinstance(exc, ExceptionGroup):
            result.extend(_filter_exception_group(exc))
        else:
            result.append(exc)
    return result


def log_exception(
    exc: BaseException,
    message: str,
    *args: Any,
    **kwargs: Any,
) -> None:
    """Log an exception with its traceback to stderr via loguru."""
    logger.opt(exception=exc).error(message, *args, **kwargs)


def apply() -> None:
    asyncio.TaskGroup = PropagatingTaskGroup  # type: ignore
    asyncio.taskgroups.TaskGroup = PropagatingTaskGroup  # type: ignore
