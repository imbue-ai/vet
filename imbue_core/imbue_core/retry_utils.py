from typing import Callable

from loguru import logger
from tenacity import RetryCallState


def _log_before_sleep(
    retry_state: RetryCallState, log_fn: Callable[[str], None]
) -> None:
    fn_name = getattr(retry_state.fn, "__name__", "unknown")
    sleep_time = (
        retry_state.next_action.sleep if retry_state.next_action is not None else 0
    )
    outcome = retry_state.outcome
    if outcome is not None:
        exception = outcome.exception()
        error_message = type(exception).__name__ + ": " + str(exception)
    else:
        error_message = "unknown"
    log_fn(
        f"Retrying {fn_name} in {sleep_time:.2f} seconds, attempt {retry_state.attempt_number} after error: {error_message}"
    )


def log_before_sleep(retry_state: RetryCallState) -> None:
    _log_before_sleep(retry_state, logger.debug)


def log_error_before_sleep(retry_state: RetryCallState) -> None:
    _log_before_sleep(retry_state, logger.error)


def log_trace_before_sleep(retry_state: RetryCallState) -> None:
    _log_before_sleep(retry_state, logger.trace)
