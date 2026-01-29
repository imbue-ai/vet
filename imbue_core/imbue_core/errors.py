"""This module contains the base errors for the Imbue applications.

Please subclass from one of the errors in this module for errors that you expect other Imbumans to handle.
"""

from typing import Any


class ImbueRuntimeException(BaseException):
    """Base class for all things that could go wrong within Imbue code.

    An ImbueRuntimeException may or may not be recoverable. Most library code should not be throwing
    ImbueRuntimeExceptions.
    """

    _was_logged_by_log_exception: bool

    def __init__(self, *args: Any) -> None:
        super().__init__(*args)
        # New instances start out marked as not-yet-logged.
        self._was_logged_by_log_exception = False


class ImbueError(ImbueRuntimeException, Exception):
    """Base class for all errors that could possibly be handled.

    When you are building the external API of your subcomponent, the errors you throw should subclass from this.
    """


class ExpectedError(ImbueError):
    """Base class for all Imbue errors that we expect to be handled.

    Use this subclass of ImbueError to represent an exception that -must- be handled by a caller. The usual use-case is
    when caller and callee are part of the same subsystem.
    """
