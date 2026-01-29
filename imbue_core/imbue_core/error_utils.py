import functools
import os
import re
import sys
import threading
import time
import traceback
from collections.abc import Callable
from collections.abc import Collection
from collections.abc import Hashable
from enum import StrEnum
from typing import Any
from typing import Iterable
from typing import Mapping
from typing import MutableMapping
from typing import assert_never

import sentry_sdk
import sentry_sdk.utils
import traceback_with_variables
from loguru import logger
from pydantic import Field
from pydantic import PrivateAttr
from sentry_sdk import HttpTransport
from sentry_sdk.attachments import Attachment
from sentry_sdk.consts import EndpointType
from sentry_sdk.envelope import Envelope
from sentry_sdk.integrations.stdlib import StdlibIntegration
from sentry_sdk.types import Event
from sentry_sdk.types import Hint
from traceback_with_variables import Format

from imbue_core.common import truncate_string
from imbue_core.pydantic_serialization import FrozenModel
from imbue_core.pydantic_serialization import MutableModel
from imbue_core.s3_uploader import upload_to_s3
from imbue_core.sentry_loguru_handler import SENTRY_LOG_FORMAT
from imbue_core.sentry_loguru_handler import SentryBreadcrumbHandler
from imbue_core.sentry_loguru_handler import SentryEventHandler
from imbue_core.sentry_loguru_handler import SentryLoguruLoggingLevels
from imbue_core.sentry_loguru_handler import log_error_inside_sentry

try:
    import brotli  # type: ignore
except ImportError:
    brotli = None


# sentry's size limits are annoyingly hard to evaluate before sending the event. we'll just try to be conservative.
# https://docs.sentry.io/concepts/data-management/size-limits/
# https://develop.sentry.dev/sdk/data-model/envelopes/#size-limits
MAX_SENTRY_ATTACHMENT_SIZE = 10 * 1024 * 1024


class SentryEventRejected(Exception):
    pass


class ExceptionKey(FrozenModel):
    exception_type: type[BaseException] | None
    exception_args: tuple[Hashable, ...]

    @classmethod
    def build_from_exception_or_fingerprint(
        cls, exception: BaseException | None, log_fingerprint: str | None
    ) -> "ExceptionKey":
        if exception is None:
            return cls(
                exception_type=None,
                exception_args=(log_fingerprint,),
            )
        else:
            return cls(
                exception_type=type(exception),
                # FIXME: we may grab things with references here unnecessarily. Let's store only the hash here and stringified representation.
                exception_args=tuple(arg for arg in exception.args if isinstance(arg, Hashable)),
            )


class ExceptionHistory(MutableModel):
    total_sent: int = 0
    total_throttled: int = 0

    last_reported_at: float | None = None  # monotonic clock value
    throttled_since_last_report: int = 0

    @property
    def since_last_report(self) -> float:
        last_reported_at = self.last_reported_at
        if last_reported_at is None:
            return float("inf")
        return time.monotonic() - last_reported_at

    def log_throttled(self):
        self.throttled_since_last_report += 1
        self.total_throttled += 1

    def log_reported(self):
        self.last_reported_at = time.monotonic()
        self.throttled_since_last_report = 0
        self.total_sent += 1


def _first_line_of_log_message(event: Event) -> str | None:
    """Extracts the first line of the log message from the event, if any."""
    message = event.get("logentry", {}).get("message")
    if message and isinstance(message, str):
        message_lines = message.strip().splitlines()
        if message_lines:
            return message_lines[0]
    return None


def _get_full_location_from_event(event: Event) -> str | None:
    """Extracts the `full_location` field that we are supposed to generate in our log handlers."""
    extra = event.get("extra", {}).get("extra")
    if extra and isinstance(extra, dict):
        full_location = extra.get("full_location")
        if full_location and isinstance(full_location, str):
            return full_location.strip() or None
    return None


class _ReasonToAllowSendingEvent(StrEnum):
    PASS_THRU = "pass_thru"
    NO_RATE_LIMIT_INFO = "no_rate_limit_info"
    TOO_MANY_TRACKED_EXCEPTIONS = "too_many_tracked_exceptions"
    INITIAL = "initial"
    INITIAL_GRACE_PERIOD = "initial_grace_period"
    TIMEOUT_ELAPSED = "timeout_elapsed"


class _SentryEventRateLimiter(MutableModel):
    """Prevent logging the same specific exceptions multiple times to sentry.

    Each allowed exception is assumed to be sent.
    """

    # these exception will never be rate limited
    pass_thru_exception_types: Collection[type[BaseException]] = Field(default_factory=set)
    # the number of initial reports to allow before starting to apply rate limiting
    initial_reports_without_rate_limiting: int = 2
    # the time (in seconds) that must pass since the last report of a given exception before allowing
    # another report it is multiplied by the number of times the exception has been passed-thru since
    # the app start after the first throttling event
    timeout_factor: float = 60.0
    # maximum number of different exceptions to track for rate limiting
    # once this number is exceeded, all events will be passed through unfiltered
    max_tracked_rate_limited_exceptions: int = 10_000

    # we should not be called in parallel, but better safe than sorry
    # this lock protects access to _exception_history, its contents, and the total counters
    _lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)
    _exception_history: MutableMapping[ExceptionKey, ExceptionHistory] = PrivateAttr(default_factory=dict)
    _total_throttled: int = PrivateAttr(default=0)
    _total_sent: int = PrivateAttr(default=0)

    def _annotate_event(
        self, event: Event, reason_to_allow: _ReasonToAllowSendingEvent, past_history: ExceptionHistory | None = None
    ) -> Event:
        logger.trace("Annotating event with rate limiter: {}", reason_to_allow)

        annotation: dict[str, Any] = {
            "reason_to_allow": reason_to_allow.value,
            "application": {
                "total_throttled": self._total_throttled,
                "total_sent": self._total_sent,
                "total_tracked": len(
                    self._exception_history
                ),  # thread-safe to read without lock since we don't care about consistency
            },
        }
        if past_history is not None:
            annotation["instance"] = {
                "since_last_report": past_history.since_last_report,
                "throttled_since_last_report": past_history.throttled_since_last_report,
                "total_throttled": past_history.total_throttled,
                "total_sent": past_history.total_sent,
            }

        event.setdefault("extra", {})
        event["extra"]["rate_limiter"] = annotation

        event.setdefault("tags", {})
        event["tags"]["rate_limiter_reason_to_allow"] = reason_to_allow
        return event

    def before_send(self, event: Event, hint: Hint) -> Event | None:
        annotated_event = self._before_send(event, hint)
        with self._lock:
            if annotated_event is None:
                self._total_throttled += 1
            else:
                self._total_sent += 1

        return annotated_event

    def _before_send(self, event: Event, hint: Hint) -> Event | None:
        exception = None
        exception_type = None
        # see sentry_sdk._types.ExcInfo which sadly we can't import
        if "exc_info" in hint:
            exception_type, exception, _ = hint["exc_info"]

        if (exception_type is not None) and (exception_type in self.pass_thru_exception_types):
            return self._annotate_event(event, _ReasonToAllowSendingEvent.PASS_THRU)

        first_line = _first_line_of_log_message(event)
        full_location = _get_full_location_from_event(event)
        if first_line and full_location:
            log_fingerprint = "\n".join([first_line, full_location])
        else:
            log_fingerprint = None

        if not (log_fingerprint or exception):
            # nothing to rate limit on
            return self._annotate_event(event, _ReasonToAllowSendingEvent.NO_RATE_LIMIT_INFO)

        key = ExceptionKey.build_from_exception_or_fingerprint(exception, log_fingerprint)
        with self._lock:
            if key not in self._exception_history:
                # we could LRU but if we got to this point, there's something else to figure out, like bad keying
                if len(self._exception_history) >= self.max_tracked_rate_limited_exceptions:
                    return self._annotate_event(event, _ReasonToAllowSendingEvent.TOO_MANY_TRACKED_EXCEPTIONS)
                history = ExceptionHistory(last_reported_at=time.monotonic(), total_sent=1)
                self._exception_history[key] = history
                return self._annotate_event(event, _ReasonToAllowSendingEvent.INITIAL)

            history = self._exception_history[key]
            reason_to_allow: _ReasonToAllowSendingEvent | None = None
            if history.total_sent < self.initial_reports_without_rate_limiting:
                reason_to_allow = _ReasonToAllowSendingEvent.INITIAL_GRACE_PERIOD
            else:
                current_timeout = self.timeout_factor * max(
                    1, history.total_sent - self.initial_reports_without_rate_limiting + 1
                )
                if history.since_last_report >= current_timeout:
                    logger.trace("Timeout elapsed for event: {}, {}", key, current_timeout)
                    reason_to_allow = _ReasonToAllowSendingEvent.TIMEOUT_ELAPSED

            if reason_to_allow:
                event = self._annotate_event(event, reason_to_allow=reason_to_allow, past_history=history)
                history.log_reported()
                return event
            history.log_throttled()

        logger.trace("Rate limiting event: {}", key)
        return None


class ImbueSentryHttpTransport(HttpTransport):
    """The sentry python sdk has pretty lame behavior if the event is too large.
    It'll just drop it, and record stats indicating that an event was dropped.
    You can see these at `https://generally-intelligent-e3.sentry.io/stats`, category "invalid".
    But there's no way to recover any information about the dropped event.

    We could try to just ensure the events don't violate the size limit, which we try to do,
    but their size limits are a bit complicated and thus hard to pre-verify. So we also want to know if anything slips through.

    The actual sentry web API does return a status code (413) if the event was rejected,
    so we need to handle this at the level of the sentry HttpTransport and do something with it.
    """

    def _send_request(
        self,
        body: bytes,
        headers: dict[str, str],
        endpoint_type: EndpointType = EndpointType.ENVELOPE,
        envelope: Envelope | None = None,
    ) -> None:
        """This is a copy of the original `_send_request` method from the HttpTransport class,
        with a hook to call `on_too_large_event` added.
        """

        def record_loss(reason: str) -> None:
            if envelope is None:
                self.record_lost_event(reason, data_category="error")
            else:
                envelope_items = envelope.items
                assert envelope_items is not None
                for item in envelope_items:
                    self.record_lost_event(reason, item=item)

        headers.update(
            {
                "User-Agent": str(self._auth.client),
                "X-Sentry-Auth": str(self._auth.to_header()),
            }
        )
        try:
            response = self._request(
                "POST",
                endpoint_type,
                body,
                headers,
            )
        except Exception:
            self.on_dropped_event("network")
            record_loss("network_error")
            raise

        try:
            self._update_rate_limits(response)

            if response.status == 429:
                # if we hit a 429.  Something was rate limited but we already
                # acted on this in `self._update_rate_limits`.  Note that we
                # do not want to record event loss here as we will have recorded
                # an outcome in relay already.
                self.on_dropped_event("status_429")

            elif response.status >= 300 or response.status < 200:
                sentry_sdk.utils.logger.error(
                    "Unexpected status code: %s (body: %s)",
                    response.status,
                    getattr(response, "data", getattr(response, "content", None)),
                )
                self.on_dropped_event("status_{}".format(response.status))
                record_loss("network_error")

                if response.status == 413:
                    assert envelope is not None
                    self.on_too_large_event(body, envelope)
        finally:
            response.close()

    def on_too_large_event(self, body: bytes, envelope: Envelope) -> None:
        """we want to log _something_ to sentry, because otherwise we have no idea what happened,
        but we also need to be super careful that this fallback doesn't itself fail.

        exceptions raised here will simply get eaten and result in nothing getting logged to sentry,
        both due to sentry's usage of `capture_internal_exceptions`
        and that we're running in a worker thread and i don't think they make an effort to re-surface exceptions from threads.
        """
        msg = "request was too large to send to sentry"
        try:
            raise SentryEventRejected(msg)
        except SentryEventRejected as e:
            stripped_envelope = Envelope(headers=envelope.headers)
            attachment_sizes = {}
            envelope_items = envelope.items
            assert envelope_items is not None
            for item in envelope_items:
                if item.data_category == "attachment":
                    payload = item.payload
                    payload_bytes_len = len(payload.get_bytes() if not isinstance(payload, (bytes, str)) else payload)
                    item_headers = item.headers
                    assert item_headers is not None
                    attachment_sizes[item_headers["filename"]] = payload_bytes_len
                    continue
                stripped_envelope.add_item(item)
            # this is uncompressed (so we can inspect it)
            serialized_stripped_envelope = stripped_envelope.serialize()

            extra: dict[str, str | int] = {
                "uncompressed_attachment_sizes": str(attachment_sizes),
                "original_compressed_request_body_size": len(body),
                "uncompressed_stripped_envelope_size": len(serialized_stripped_envelope),
            }

            # send stripped envelope to S3 -- is preceding code now overkill?
            upload_name = upload_to_s3("stripped_envelope", ".txt", serialized_stripped_envelope)

            log_error_inside_sentry(e, msg, extra=extra, additional_s3_uploads=(upload_name,) if upload_name else None)


def get_traceback_with_vars(exception: BaseException | None = None) -> str:
    # be careful of potential performance regressions with increasing these limits
    tb_format = Format(max_value_str_len=100_000, max_exc_str_len=2_000_000)
    if exception is None:
        # no exception passed in; get the current exception. this will still be None if not in an exception handler
        exception = sys.exception()
    try:
        if exception is not None:
            # we are in an exception handler, use that for the traceback
            # for some reason this breaks when casting to an `Exception`, so just using type: ignore
            return traceback_with_variables.format_exc(exception, fmt=tb_format)  # type: ignore
        else:
            # not in an exception handler, just get the current stack
            return traceback_with_variables.format_cur_tb(fmt=tb_format)
    except Exception as e:
        return f"got exception while formatting traceback with `traceback_with_variables`: {traceback.format_exception(e)}"


def _default_sentry_add_extra_info_hook(event: Event, hint: Hint) -> tuple[Event, Hint, tuple[Callable, ...]]:
    """Add traceback with variables to the event as an attachment."""
    # TODO: We just use sentry attachments here; we could also upload to S3, but figure this hook is itself a fallback, so leaving it for now?
    expected_attachments = []
    tb_with_vars = truncate_string(get_traceback_with_vars(), MAX_SENTRY_ATTACHMENT_SIZE)
    hint["attachments"].append(Attachment(tb_with_vars.encode(), filename="traceback_with_variables.txt"))
    expected_attachments.append("traceback_with_variables.txt")
    # record the names of the expected attachments just in case there's any weirdness about attachments not showing up
    event.setdefault("extra", {})["expected_attachments"] = str(expected_attachments)
    return event, hint, ()


# We define BeforeSendType here to be one or more callables that match the signature of sentry's before_send hook.
# The event will be passed through each one in our wrapping code.
BaseBeforeSendType = Callable[[Event, Hint], Event | None]
BeforeSendType = BaseBeforeSendType | list[BaseBeforeSendType]


# NOTE: if the actual event (without attachments) being too large is a problem, then it will be handled
#       in our custom logic in ImbueSentryHttpTransport above.
def _before_send_wrapper(
    event: Event,
    hint: Hint,
    before_send_list: Iterable[BaseBeforeSendType],
) -> Event | None:
    try:
        for before_send in before_send_list:
            # pyre-fixme[9]: the result of before_send can be None which is not compatible with event annotation.
            event = before_send(event, hint)
            if event is None:
                return None

        return event
    except Exception as e:
        # It is critical that we catch errors here and print them, because this is called from sentry
        # Failing to do so means that we will see NOTHING about the failure!
        # See this PR for more: https://gitlab.com/generally-intelligent/generally_intelligent/-/merge_requests/5789
        #
        # Questions to the above:
        # - why are we not relying on the Sentry's logger for this?
        # - won't the call to `logger.exception` itself try to send something to Sentry causing recursion?
        # - the following message will likely hit an error inside Loguru handler because it is not allowed
        #   to call emit from inside emit (that's what we're in here).
        logger.exception("Failure when processing event in before_send hook: {}", e)
        # NOTE: this re-raise will get suppressed by Sentry and treated as if `before_send` returned `None`
        raise


def _fixup_release_id(release_id: str) -> str:
    """
    For pre-release release candidate versions, Sentry requires the release ID to be in the semver format.

    E.g. "0.1.0rc1" should be converted to "0.1.0-rc.1".

    """
    return re.sub(r"(\d+\.\d+\.\d+)rc(\d+)", r"\1-rc.\2", release_id)


def setup_sentry(
    dsn: str,
    release_id: str,
    global_user_context: Mapping[str, str] | None = None,
    integrations: tuple[Any, ...] = (),
    before_send: BeforeSendType | None = None,
    add_extra_info_hook: Callable[[Event, Hint], tuple[Event, Hint, tuple[Callable, ...]]] | None = None,
    environment: str | None = None,
) -> None:
    """Sets up the main Sentry instance for this process.

    This should be done *after* setting up normal loguru loggers, to ensure that sentry handling happens after normal logging.
    In case the sentry stuff hangs or something odd, we want to make sure to at least get regular log output.

    Args:
        ...
        add_extra_info_hook: If provided, this function will be called with the event at Handle time.
        before_send: If provided, this function (or list of functions) will be called in order to handle and mutate the event before sending to Sentry.
    """
    assert "SENTRY_DSN" not in os.environ, (
        "Please `unset SENTRY_DSN` in your environment. Set the DSN via the server settings FRONTEND_SENTRY_DSN and BACKEND_SENTRY_DSN instead."
    )

    before_send_unrolled = []

    if isinstance(before_send, list):
        before_send_unrolled = list(before_send)
    elif callable(before_send):
        before_send_unrolled = [before_send]
    elif before_send is None:
        pass
    else:
        assert_never(before_send)

    # NOTE: the rate limiter object's lifetime is maintained by being captured in the
    #       closure of the before_send function
    rate_limiter = _SentryEventRateLimiter()
    before_send_unrolled.append(rate_limiter.before_send)

    before_send = functools.partial(
        _before_send_wrapper,
        before_send_list=before_send_unrolled,
    )

    sentry_sdk.init(
        sample_rate=1.0,
        environment=environment,
        traces_sample_rate=1.0,
        # required for `logger.error` calls to include stacktraces
        attach_stacktrace=True,
        # note this will capture unhandled exceptions even if not explicitly logged, among other things
        # https://docs.sentry.io/platforms/python/integrations/default-integrations/
        default_integrations=True,
        # this doesn't affect the default integrations, but prevents any other ones from being added automatically
        auto_enabling_integrations=False,
        integrations=[
            *integrations,
        ],
        disabled_integrations=[
            # this only adds hooks to subprocess and httplib, which imo just adds noisy breadcrumbs.
            StdlibIntegration()
        ],
        dsn=dsn,
        # may want to get more restrictive about this in the future
        # see https://docs.sentry.io/platforms/python/data-management/data-collected/
        send_default_pii=True,
        # sentry has a max payload size of 1MB, so we can't make this infinite
        max_value_length=10_000,
        add_full_stack=True,
        before_send=before_send,
        release=_fixup_release_id(release_id),
        # default is 100; can't make it too large because total event size must be <1MB
        max_breadcrumbs=100,
        # if the locals is very large, sentry gets to be quite slow to log errors if this is enabled.
        # we log our own traceback_with_variables anyways.
        include_local_variables=False,
        transport=ImbueSentryHttpTransport,
    )
    logger.info("Sentry initialized")

    if global_user_context is not None:
        sentry_sdk.set_user(dict(global_user_context))

    # capture loguru errors/exceptions with a custom handler
    min_sentry_level: int = SentryLoguruLoggingLevels.LOW_PRIORITY.value
    handler = SentryEventHandler(
        level=min_sentry_level,
        add_extra_info_hook=add_extra_info_hook or _default_sentry_add_extra_info_hook,
    )
    register_sentry_event_handler(handler)
    logger.add(
        handler,
        level=min_sentry_level,
        diagnose=False,
        format=SENTRY_LOG_FORMAT,
    )
    # capture lower level loguru messages to add as breadcrumbs on events
    # the extra info is not helpful here and makes the breadcrumbs larger; they're still available in the log file attachment
    breadcrumb_level: int = SentryLoguruLoggingLevels.INFO.value
    logger.add(
        SentryBreadcrumbHandler(level=breadcrumb_level, strip_extra=True),
        level=breadcrumb_level,
        diagnose=False,
        format=SENTRY_LOG_FORMAT,
    )


_SENTRY_EVENT_HANDLER: SentryEventHandler | None = None


def register_sentry_event_handler(handler: SentryEventHandler) -> None:
    global _SENTRY_EVENT_HANDLER
    _SENTRY_EVENT_HANDLER = handler


def get_sentry_event_handler() -> SentryEventHandler | None:
    return _SENTRY_EVENT_HANDLER
