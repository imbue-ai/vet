# mypy: ignore-errors # TODO: @josh to fix the types in this file ;)
import asyncio
import os
from asyncio import Task
from contextvars import ContextVar
from contextvars import copy_context
from typing import Any
from typing import Coroutine
from typing import TypeVar

from loguru import logger

from imbue_core.async_monkey_patches import log_exception
from imbue_core.async_monkey_patches import safe_cancel
from imbue_core.async_monkey_patches import safe_cancel_multiple_and_wait_for_cleanup

CURRENT_TASK_GROUP_FOR_SIMPLE_EXECUTION = ContextVar[asyncio.TaskGroup | None]("The current task group for this task")
CURRENT_TASK_GROUP_FOR_SIMPLE_EXECUTION.set(None)


T = TypeVar("T")

SET_TO_FALSE_TO_IGNORE_RAISING_DURING_TESTING_UGH_SO_EXCITED_FOR_NO_ASYNCIO = True


def create_clean_task(
    # the hammer to run
    coro: Coroutine[Any, Any, T],
    # a name to assign to the hammer Task. By default, it will be f"{function.__name__} ({hammer_id})"
    name: str | None = None,
    # if true, will create a new containing task group rather than adding to the current one
    is_within_new_group: bool = False,
) -> Task:
    """
    Use this method to create a Task (rather than using asyncio.create_task directly).

    The interface is roughly the same, except that the tasks will be added to a task group for this task, if it exists,
    so that they can be properly cleaned up when the task finishes.

    The main reason you want something like this is that it's an antipattern to make async tasks without thinking
    about what group they are part of (they can be left running afterward, which usually leads to bugs).
    See this excellent blog post for more details:
    https://vorpus.org/blog/notes-on-structured-concurrency-or-go-statement-considered-harmful/
    """

    current_task_group = CURRENT_TASK_GROUP_FOR_SIMPLE_EXECUTION.get()
    if is_within_new_group:
        context = copy_context()
        new_task_group = asyncio.TaskGroup()
        # noinspection PyArgumentList
        task = asyncio.create_task(
            _run_clean_task_in_group(new_task_group, coro, name=name, context=context),
            name=f"wrapper for {name}",
            context=context,
        )
        task.owned_task_group = new_task_group  # pyre-ignore[16]: this appears unused but is for debugging
    else:
        if current_task_group is None:
            raise Exception(
                "Clean tasks must be started from another clean task, or by setting is_within_new_group to True (and being careful to actually close that task appropriately)"
            )
        else:
            task = current_task_group.create_task(coro, name=name)
            task.task_group = current_task_group  # pyre-ignore[16]: this appears unused but is for debugging
    return task


async def _run_clean_task_in_group(
    task_group: asyncio.TaskGroup, coro: Coroutine[Any, Any, T], name: str | None, context: Any
) -> T | None:
    """We define that in generally, no exceptions will escape this context.

    Only KeyboardInterrupt and CancelledError are allowed to escape for specific reasons described below.
    """
    try:
        this_task = asyncio.current_task()
        assert this_task is not None
        # TODO: just for typing purposes, we may want to explicitly invoke our PropagatingTaskGroup here instead
        #  then we can make methods that call safe_cancel on all tasks in the group, etc
        async with task_group:
            # pyre-fixme[16]: pyre doesn't know about name
            task_group.name = "for " + this_task.get_name()
            this_task.task_group = task_group  # pyre-ignore[16]: this appears unused but is for debugging
            CURRENT_TASK_GROUP_FOR_SIMPLE_EXECUTION.set(task_group)
            inner_task = task_group.create_task(coro, name=name, context=context)
            inner_task.task_group = task_group  # pyre-ignore[16]: this appears unused but is for debugging
            try:
                result = await inner_task
            except asyncio.CancelledError:
                if getattr(this_task, "is_being_canceled_by_us", None):
                    for task in task_group._tasks:
                        safe_cancel(task)
                    # must also cancel the actual task, as this cancellation may be for this task, not that one
                    safe_cancel(inner_task)
                    return None
                raise
            # We want to ensure that the "source" of cancellation is this code.
            # Otherwise, we could add a task that raises an exception to the group
            # to cancel the rest of the group without reaching into private attributes.
            logger.debug(
                "Cancelling all tasks in this task group because the task exited normally: {}", this_task.get_name()
            )
            to_cancel = []
            for task in task_group._tasks:
                if not task.done():
                    to_cancel.append(task)
            # FIXME: the above calls to safe_cancel() really probably need to be changed to this as well...
            #  or at least we ought to await all of the tasks (that are not our own)
            # we MUST wait here for each of the tasks to have been cancelled, otherwise we end up with some
            # pretty hard to track down bugs (which are fixed by doing this)
            # basically you can end up causing a canceled error in some lower level library, but not reaping it
            # until some other poor, totally unrelated task later comes along and tries to do something innocent
            # and then it looks like it was canceled, which means that it effectively silently disappears!
            # this whole thing is just super annoying
            await safe_cancel_multiple_and_wait_for_cleanup(to_cancel)
            logger.debug("Done cancelling tasks, returning: {}", this_task.get_name())
        return result
    except asyncio.CancelledError:
        # Let's let this CancelledError propagate outwards.
        raise
    except KeyboardInterrupt:
        # The user is trying to cancel the program, let us respect them by letting this propagate outwards.
        raise
    except BaseException as e:
        log_exception(e, "Clean task failed and was never retrieved")
        is_testing = "PYTEST_CURRENT_TEST" in os.environ
        if is_testing:
            if SET_TO_FALSE_TO_IGNORE_RAISING_DURING_TESTING_UGH_SO_EXCITED_FOR_NO_ASYNCIO:
                raise
    return None
