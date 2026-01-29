from contextlib import contextmanager
from typing import Any
from typing import Callable
from typing import Generator
from typing import Iterator

import pytest
from loguru import logger

from imbue_core.async_monkey_patches import log_exception
from imbue_core.constants import ExceptionPriority


class IncorrectErrorsLoggedDuringTesting(Exception):
    pass


@contextmanager
def check_logged_errors(check_func: Callable[[list[str]], None]) -> Iterator[None]:
    """Context manager that monkey patches logger._log to accumulate error messages instead of logging them.
    Then it runs the check function on the accumulated errors."""
    original_log_func = (
        logger._log
    )  # pyre-fixme[16]: pyre doesn't know that _log exists
    accumulated_errors: list[str] = []

    error_level_names = (
        "ERROR",
        ExceptionPriority.LOW_PRIORITY.value,
        ExceptionPriority.MEDIUM_PRIORITY.value,
        ExceptionPriority.HIGH_PRIORITY.value,
    )

    logger._log = lambda level, flag, options, message, args, kwargs: (
        (
            accumulated_errors.append(message) is None
            and original_log_func(
                "INFO",
                flag,
                options,
                "CAUGHT ERROR LOG: " + message.splitlines()[0][:100],
                args,
                kwargs,
            )
        )
        if level in error_level_names
        else original_log_func(level, flag, options, message, args, kwargs)
    )
    try:
        yield
    finally:
        logger._log = original_log_func
        check_func(accumulated_errors)


def at_least_check_maker(expected_errors_set: set[str]) -> Callable[[list[str]], None]:
    assert isinstance(expected_errors_set, set), "expected_errors must be a set"
    expected_errors = list(expected_errors_set)

    def check_func(accumulated_errors: list[str]) -> None:
        if len(accumulated_errors) < len(expected_errors):
            raise IncorrectErrorsLoggedDuringTesting(
                f"{len(accumulated_errors)=} != {len(expected_errors)=}, {accumulated_errors=}"
            )
        for expected_error in expected_errors:
            for accumulated_error in accumulated_errors:
                if expected_error in accumulated_error:
                    break
            else:
                raise IncorrectErrorsLoggedDuringTesting(
                    f"{expected_error=} is not in {accumulated_errors=}"
                )

    return check_func


@contextmanager
def expect_at_least_logged_errors(expected_errors: set[str]) -> Iterator[None]:
    """Context manager that monkey patches logger._log to accumulate error messages instead of logging them.
    Checks that all expected errors are in the accumulated errors, in no particular order.
    """
    check_func = at_least_check_maker(expected_errors)
    with check_logged_errors(check_func):
        yield


def exact_check_maker(expected_errors: list[str]) -> Callable[[list[str]], None]:
    assert isinstance(expected_errors, list), "expected_errors must be a list"

    def check_func(accumulated_errors: list[str]) -> None:
        if len(accumulated_errors) != len(expected_errors):
            raise IncorrectErrorsLoggedDuringTesting(
                f"{len(accumulated_errors)=} != {len(expected_errors)=}, {accumulated_errors=}"
            )
        for i, expected_error in enumerate(expected_errors):
            if expected_error not in accumulated_errors[i]:
                raise IncorrectErrorsLoggedDuringTesting(
                    f"At position {i=}, {expected_error=} is not in {accumulated_errors[i]=}"
                )

    return check_func


@contextmanager
def expect_exact_logged_errors(expected_errors: list[str]) -> Iterator[None]:
    """Context manager that monkey patches logger._log to accumulate error messages instead of logging them.
    Checks that all expected errors are in the accumulated errors, in the same order."""
    check_func = exact_check_maker(expected_errors)
    with check_logged_errors(check_func):
        yield


def test_log_exception() -> None:
    with expect_exact_logged_errors(["Test log_exception"]):
        try:
            x = 1 / 0
        except Exception as e:
            log_exception(e, "Test log_exception")
            assert True  # If we reach here, the test passes
        else:
            assert False, "log_exception did not raise an exception"


def test_log_exception_with_priority() -> None:
    # ensure_core_log_levels_configured auto-used in conftest
    with expect_exact_logged_errors(["Test log_exception"]):
        try:
            x = 1 / 0
        except Exception as e:
            log_exception(
                e, "Test log_exception", priority=ExceptionPriority.LOW_PRIORITY
            )
            assert True  # If we reach here, the test passes
        else:
            assert False, "log_exception did not raise an exception"


@pytest.fixture
def explode_on_error() -> Generator[None, None, None]:
    """Fixture to explode on error."""
    original_log_func = (
        logger._log
    )  # pyre-fixme[16]: pyre doesn't know that _log exists
    accumulated_errors: list[str] = []

    def _log_wrapper(
        level: str,
        flag: int,
        options: tuple[int, ...],
        message: str,
        args: tuple,
        kwargs: dict,
    ) -> Any:
        if level == "ERROR":
            accumulated_errors.append(message)
        new_options = list(options)
        new_options[1] = 1
        return original_log_func(level, flag, tuple(new_options), message, args, kwargs)

    logger._log = _log_wrapper

    try:
        yield
    except BaseException:
        raise
    else:
        if len(accumulated_errors) > 0:
            raise IncorrectErrorsLoggedDuringTesting(
                f"Errors logged during testing: {accumulated_errors}"
            )
    finally:
        logger._log = original_log_func


def test_log_error(explode_on_error: Any) -> None:
    with expect_exact_logged_errors(["Something bad happened"]):
        logger.error("Something bad happened")

    with pytest.raises(IncorrectErrorsLoggedDuringTesting):
        with expect_exact_logged_errors(["Something bad happened"]):
            pass

    with pytest.raises(IncorrectErrorsLoggedDuringTesting):
        with expect_exact_logged_errors(["Something bad happened"]):
            logger.error("Something bad happened")
            logger.error("Something else bad happened")


def test_log_error_at_least(explode_on_error: Any) -> None:
    with expect_at_least_logged_errors({"Something bad happened"}):
        logger.error("Something bad happened")
        logger.error("Something else bad happened")

    with pytest.raises(IncorrectErrorsLoggedDuringTesting):
        with expect_at_least_logged_errors(
            {"Something bad happened", "Something else bad happened"}
        ):
            logger.error("Something bad happened")
