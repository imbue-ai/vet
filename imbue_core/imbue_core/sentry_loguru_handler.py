"""
inlines sentry_sdk.integrations.loguru and sentry_sdk.integrations.logging, so we can make some changes.
i'm intentionally keeping most of the old logic so this still behaves roughly as expected/documented.

we probably could/should go through and fully streamline this though to do just what we need.

The changes so far (could be out of date):
- adds `strip_extra` to the breadcrumb handler
- adds `add_extra_info_hook` to the event handler, with a watchdog to make sure it doesn't slow things down
"""

import asyncio
import enum
import logging
from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import wait
from datetime import datetime
from datetime import timezone
from fnmatch import fnmatch
from typing import Any
from typing import Callable
from typing import Iterable
from typing import Sequence

import sentry_sdk
from loguru import logger
from sentry_sdk import new_scope

# "This disables recording (both in breadcrumbs and as events) calls to a logger of a specific name.  Among other uses, many of our integrations
# use this to prevent their actions being recorded as breadcrumbs. Exposed to users as a way to quiet spammy loggers."
# We have to import it so that existing setters work properly
from sentry_sdk.integrations.logging import _IGNORED_LOGGERS
from sentry_sdk.types import Event
from sentry_sdk.types import Hint
from sentry_sdk.utils import current_stacktrace
from sentry_sdk.utils import event_from_exception
from sentry_sdk.utils import to_string

from imbue_core.constants import HIGH_PRIORITY_LEVEL
from imbue_core.constants import LOW_PRIORITY_LEVEL
from imbue_core.constants import MEDIUM_PRIORITY_LEVEL
from imbue_core.s3_uploader import EXTRAS_UPLOADED_FILES_KEY

# for formatting the log message. we don't want the timestamp/level because sentry already tracks that,
# and it messes up event grouping since this string becomes the event title.
SENTRY_LOG_FORMAT = "{name}:{function}:{line} - {message}"


class SentryLoguruLoggingLevels(enum.IntEnum):
    TRACE = 5
    DEBUG = 10
    INFO = 20
    SUCCESS = 25
    WARNING = 30
    # Additional loguru levels for sentry hot-wiring that we also present with custom colors in the console.
    # The mapping to sentry levels for both breadcrumbs and reporting is done in map_to_sentry_name()
    LOW_PRIORITY = LOW_PRIORITY_LEVEL  # pyre-ignore[8]: pyre doesn't understand enums
    MEDIUM_PRIORITY = MEDIUM_PRIORITY_LEVEL  # pyre-ignore[8]: pyre doesn't understand enums
    HIGH_PRIORITY = HIGH_PRIORITY_LEVEL  # pyre-ignore[8]: pyre doesn't understand enums
    ERROR = 40
    CRITICAL = 50

    def map_to_sentry_name(self) -> str:
        # Sentry only understands and respects "debug", "info", "warning", "error", "critical", "fatal"
        match self:
            case SentryLoguruLoggingLevels.TRACE | SentryLoguruLoggingLevels.DEBUG:
                return "debug"
            case SentryLoguruLoggingLevels.INFO | SentryLoguruLoggingLevels.SUCCESS:
                return "info"
            case SentryLoguruLoggingLevels.LOW_PRIORITY:
                return "info"
            case SentryLoguruLoggingLevels.MEDIUM_PRIORITY | SentryLoguruLoggingLevels.WARNING:
                return "warning"
            case SentryLoguruLoggingLevels.HIGH_PRIORITY | SentryLoguruLoggingLevels.ERROR:
                return "error"
            case SentryLoguruLoggingLevels.CRITICAL:
                return "critical"
            case _:
                return ""


class _BaseHandler(logging.Handler):
    COMMON_RECORD_ATTRS = frozenset(
        (
            "args",
            "created",
            "exc_info",
            "exc_text",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "linenno",
            "lineno",
            "message",
            "module",
            "msecs",
            "msg",
            "name",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack",
            "tags",
            "taskName",
            "thread",
            "threadName",
            "stack_info",
        )
    )

    def _can_record(self, record: logging.LogRecord) -> bool:
        """Prevents ignored loggers from recording"""
        for logger in _IGNORED_LOGGERS:
            if fnmatch(record.name, logger):
                return False
        return True

    def _extra_from_record(self, record: logging.LogRecord) -> dict[str, object]:
        return {
            k: v
            for k, v in vars(record).items()
            if k not in self.COMMON_RECORD_ATTRS and (not isinstance(k, str) or not k.startswith("_"))
        }

    def _logging_to_event_level(self, record: logging.LogRecord) -> str:
        try:
            return SentryLoguruLoggingLevels(record.levelno).map_to_sentry_name()
        except ValueError:
            return record.levelname.lower() if record.levelname else ""


def _wrap_callback(callback: Callable) -> None:
    try:
        callback()
    except Exception as e:
        log_error_inside_sentry(e, "Sentry callback raised")


class SentryEventHandler(_BaseHandler):
    """A logging handler that emits Sentry events for each log record."""

    def __init__(
        self,
        level: int = logging.NOTSET,
        add_extra_info_hook: Callable[[Event, Hint], tuple[Event, Hint, tuple[Callable, ...]]] | None = None,
    ) -> None:
        super().__init__(level=level)
        self.add_extra_info_hook = add_extra_info_hook
        self.add_extra_info_previously_timed_out = False
        self._executor: ThreadPoolExecutor | None = ThreadPoolExecutor()
        self._futures: list[Future] = []

    def emit(self, record: logging.LogRecord) -> Any:
        self.format(record)
        return self._emit(record)

    def schedule_callbacks(self, callbacks: Sequence[Callable]) -> None:
        executor = self._executor
        if executor is not None:
            logger.info(f"Sentry event handler registered {len(callbacks)} callbacks with an executor")
            for callback in callbacks:
                future = executor.submit(lambda c=callback: _wrap_callback(c))
                self._futures.append(future)
        else:
            logger.debug(
                f"Sentry event handler failed to register {len(callbacks)} callbacks because no executor was found"
            )

    def close(self) -> None:
        executor = self._executor
        if executor is not None:
            executor.shutdown(wait=False)
            wait(self._futures, timeout=5.0)
            self._executor = None
        super().close()

    def _emit(self, record: logging.LogRecord) -> None:
        if not self._can_record(record):
            return

        # Filter out KeyboardInterrupt and CancelledError exceptions from being logged to Sentry
        if record.exc_info and record.exc_info[0] is not None:
            exc_type = record.exc_info[0]
            if exc_type is KeyboardInterrupt or exc_type is asyncio.CancelledError:
                return

        client = sentry_sdk.get_client()
        if not client.is_active():
            return

        client_options = client.options

        # exc_info might be None or (None, None, None)
        #
        # exc_info may also be any falsy value due to Python stdlib being
        # liberal with what it receives and Celery's billiard being "liberal"
        # with what it sends. See
        # https://github.com/getsentry/sentry-python/issues/904
        if record.exc_info and record.exc_info[0] is not None:
            event, hint = event_from_exception(
                record.exc_info,
                client_options=client_options,
                mechanism={"type": "logging", "handled": True},
            )
        elif (record.exc_info and record.exc_info[0] is None) or record.stack_info:
            event: Event = {}
            hint: Hint = {}
            event["threads"] = {
                "values": [
                    {
                        "stacktrace": current_stacktrace(
                            include_local_variables=client_options["include_local_variables"],
                            max_value_length=client_options["max_value_length"],
                        ),
                        "crashed": False,
                        "current": True,
                    }
                ]
            }
        else:
            event: Event = {}
            hint: Hint = {}

        hint["log_record"] = record

        level = self._logging_to_event_level(record)
        if level in {"debug", "info", "warning", "error", "critical", "fatal"}:
            # standard levels that sentry understands, it ignores any other types
            event["level"] = level  # type: ignore[typeddict-item]

        event["logger"] = record.name

        # Log records from `warnings` module as separate issues
        record_captured_from_warnings_module = record.name == "py.warnings" and record.msg == "%s"
        if record_captured_from_warnings_module:
            # use the actual message and not "%s" as the message
            # this prevents grouping all warnings under one "%s" issue
            msg = record.args[0]  # type: ignore

            event["logentry"] = {
                "message": msg,
                "params": (),
            }

        else:
            event["logentry"] = {
                # TODO: a bit lame, but we don't have access to the unformatted message, so we just reverse our current format...
                "message": to_string(record.msg).split(" - ")[-1],
                "params": record.args,
            }

        event["extra"] = self._extra_from_record(record)

        if self.add_extra_info_hook:
            event, hint, callbacks = self.add_extra_with_watchdog(event, hint, timeout=1)
            self.schedule_callbacks(callbacks)

        sentry_sdk.capture_event(event, hint)

    def add_extra_with_watchdog(
        self, event: Event, hint: Hint, timeout: float
    ) -> tuple[Event, Hint, tuple[Callable, ...]]:
        """Call the add_extra_info_hook with a watchdog so we can skip it if it's slow, and get another sentry error about that."""
        if self.add_extra_info_previously_timed_out:
            event.setdefault("extra", {})["add_extra_info_previously_timed_out"] = True
            return event, hint, tuple()
        if "attachments" not in hint:
            hint["attachments"] = []
        executor = ThreadPoolExecutor()
        add_extra_info_hook = self.add_extra_info_hook
        assert add_extra_info_hook is not None
        future = executor.submit(add_extra_info_hook, event, hint)
        try:
            event, hint, callbacks = future.result(timeout=timeout)
            executor.shutdown()
            return event, hint, callbacks
        except TimeoutError as e:
            from imbue_core.sculptor.telemetry import ProductComponent
            from imbue_core.sculptor.telemetry import SculptorPosthogEvent
            from imbue_core.sculptor.telemetry import send_exception_to_posthog

            send_exception_to_posthog(
                SculptorPosthogEvent.SENTRY_EXCEPTION_DATA_COLLECTION_TOO_SLOW,
                e,
                component=ProductComponent.CROSS_COMPONENT,
            )
            # this will leave the thread still running; there's no real way to cancel it.
            # we'll at least set this flag so future errors don't try to run the (bugged?) hook again.
            executor.shutdown(wait=False)
            self.add_extra_info_previously_timed_out = True

        # continue with the main event without the extra info
        return event, hint, tuple()


class SentryBreadcrumbHandler(_BaseHandler):
    """
    A logging handler that records breadcrumbs for each log record.

    Note that you do not have to use this class if the logging integration is enabled, which it is by default.
    """

    def __init__(self, level: int = logging.NOTSET, strip_extra: bool = False) -> None:
        super().__init__(level=level)
        self.strip_extra = strip_extra

    def emit(self, record: logging.LogRecord) -> Any:
        # is this needed? keeping in case there are side effects that we want to trigger here
        self.format(record)
        return self._emit(record)

    def _emit(self, record: logging.LogRecord) -> None:
        if not self._can_record(record):
            return

        sentry_sdk.add_breadcrumb(self._breadcrumb_from_record(record), hint={"log_record": record})

    def _breadcrumb_from_record(self, record: logging.LogRecord) -> dict[str, Any]:
        return {
            "type": "log",
            "level": self._logging_to_event_level(record),
            "category": record.name,
            "message": record.message,
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc),
            "data": self._extra_from_record(record) if not self.strip_extra else {},
        }


def log_error_inside_sentry(
    exception: Exception,
    message: str,
    extra: dict[str, str | int] | None = None,
    additional_s3_uploads: Iterable[str] | None = None,
) -> None:
    """Log an error to sentry that happens during processing of a sentry event.

    This needs to be done very carefully to ensure it won't fail - we don't want to have to have a fallback-fallback handler.
    The caller should ensure everything passed into this is small so there's no chance of size issues.
    """
    client = sentry_sdk.get_client()
    # we want to get rid of any breadcrumbs, attachments, and other stuff that might have caused the original request to fail.
    # this will obviously make it harder to debug; we may want to selectively add some of this back.
    with new_scope() as scope:
        scope.clear()
        event, hint = event_from_exception(
            exception,
            client_options=client.options,
            mechanism={"type": "watchdog", "handled": True},
        )
        event["message"] = message
        if extra is not None:
            if "extra" not in event:
                event["extra"] = {}
            for k, v in extra.items():
                event["extra"][k] = v

        # record any other files uploaded to s3
        if additional_s3_uploads is not None:
            event["extra"][EXTRAS_UPLOADED_FILES_KEY + "_erred"] = str(list(additional_s3_uploads))

        # Note that new_scope() gives a new "current scope" but doesn't affect the global or isolation scope,
        # which is where most info is actually stored. Typically all 3 scopes are merged before logging the event.
        # So we'll make sure to call capture_event in such a way that this merging doesn't happen.
        client.capture_event(event=event, hint=hint, scope=scope)
