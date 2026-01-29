import threading
from typing import Any
from typing import Callable

from loguru import logger

from imbue_core.async_monkey_patches import log_exception
from imbue_core.sculptor.telemetry import flush_sentry_and_exit_program
from imbue_core.sculptor.telemetry import send_exception_to_posthog
from imbue_core.sculptor.telemetry_constants import SculptorPosthogEvent

# Should be in sync with sculptor.constants.SCULPTOR_EXIT_CODE_IRRECOVERABLE_ERROR
EXIT_CODE_IRRECOVERABLE_ERROR = 3


_default_is_irrecoverable_exception = lambda e: False

_IS_IRRECOVERABLE_EXCEPTION_HANDLER = _default_is_irrecoverable_exception


def _is_match_for_enumerated_exceptions(
    exception_or_exception_group: BaseException | ExceptionGroup,
    enumerated_exceptions: tuple[type[BaseException], ...],
) -> bool:
    """
    Return True if:
        - we get a single exception and it is an instance of one of the enumerated exceptions
        - or we get an ExceptionGroup and all of its contained exceptions are instances of one of the enumerated exceptions

    """
    if not isinstance(exception_or_exception_group, ExceptionGroup):
        return isinstance(exception_or_exception_group, enumerated_exceptions)
    return all(
        _is_match_for_enumerated_exceptions(e, enumerated_exceptions) for e in exception_or_exception_group.exceptions
    )


class ObservableThread(threading.Thread):
    """Thread that captures exceptions and returns results."""

    def __init__(
        self,
        target: Callable[..., Any],
        args: tuple = (),
        kwargs: dict | None = None,
        name: str | None = None,
        daemon: bool = True,
        silenced_exceptions: tuple[type[BaseException], ...] | None = None,
        suppressed_exceptions: tuple[type[BaseException], ...] | None = None,
    ) -> None:
        """Initialize ObservableThread.

        Args:
            target: Function to run
            args: Positional arguments for target
            kwargs: Keyword arguments for target
            name: Thread name
            daemon: Whether thread is daemon
            silenced_exceptions: Exceptions that are not logged
            suppressed_exceptions: Exceptions that are not re-raised
        """
        super().__init__(name=name, daemon=daemon)
        self._target = target
        self._target_name = target.__name__ if target else None
        self._args = args  # TODO: Why do we keep this here?  It doesn't seem to be used.
        self._kwargs = kwargs or {}  # Same.
        self._exception: BaseException | None = None
        self._silenced_exceptions = silenced_exceptions or ()
        self._suppressed_exceptions = suppressed_exceptions or ()

    @classmethod
    def set_irrecoverable_exception_handler(cls, handler: Callable[[BaseException], bool]) -> None:
        """Set the global handler to determine if an exception is irrecoverable."""
        global _IS_IRRECOVERABLE_EXCEPTION_HANDLER
        _IS_IRRECOVERABLE_EXCEPTION_HANDLER = handler

    @property
    def target_name(self) -> str | None:
        return self._target_name

    def run(self) -> None:
        """Run the target function."""
        try:
            super().run()
        except BaseException as e:
            if _IS_IRRECOVERABLE_EXCEPTION_HANDLER(e):
                logger.opt(exception=e).info(
                    "Irrecoverable error in thread '{}' with target '{}'. Terminating immediately.",
                    self.name,
                    self.target_name,
                )
                send_exception_to_posthog(SculptorPosthogEvent.THREAD_IRRECOVERABLE_EXCEPTION, e)
                flush_sentry_and_exit_program(
                    EXIT_CODE_IRRECOVERABLE_ERROR,
                    "Irrecoverable exception encountered (see logs for details).",
                )
            self._exception = e
            if _is_match_for_enumerated_exceptions(e, self._silenced_exceptions):
                return
            else:
                log_exception(
                    e,
                    "Error in in thread '{name}' with target '{target_name}'",
                    name=self.name,
                    target_name=self.target_name,
                )
                raise

    def join(self, timeout: float | None = None) -> None:
        """Wait for thread completion and return result or raise exception.

        Args:
            timeout: Max time to wait

        Returns: None

        Raises:
            The exception raised by target function, if any, unless it is in the suppressed_exceptions list
        """
        super().join(timeout)
        self.maybe_raise()

    def maybe_raise(self) -> None:
        exception = self.exception_if_not_suppressed
        if exception:
            raise exception

    @property
    def exception_raw(self) -> BaseException | None:
        """Get the exception raised in the thread if any (without re-raising)."""
        return self._exception

    @property
    def exception_if_not_suppressed(self) -> BaseException | None:
        """
        Get the exception raised in the thread if any, unless it is in the suppressed_exceptions list.

        """
        if self._exception and not _is_match_for_enumerated_exceptions(self._exception, self._suppressed_exceptions):
            return self._exception
