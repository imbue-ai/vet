"""Test utilities for async_monkey_patches - provides fixtures for catching logged errors during tests."""

import sys
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any
from typing import Callable
from typing import Generator
from typing import Iterator

import pytest
from loguru import logger

from imbue_core.async_monkey_patches import log_exception


class IncorrectErrorsLoggedDuringTesting(Exception):
    pass


_expecting_errors: ContextVar[bool] = ContextVar("expecting_errors", default=False)


@contextmanager
def check_logged_errors(check_func: Callable[[list[str]], None]) -> Iterator[None]:
    """Context manager that intercepts ERROR logs using loguru's sink system.
    Then it runs the check function on the accumulated errors.

    Sets the _expecting_errors context variable so that explode_on_error knows to
    ignore errors during this block.
    """
    accumulated_errors: list[str] = []

    # Set the context variable to indicate we're expecting errors
    token = _expecting_errors.set(True)

    def error_catching_sink(message: Any) -> None:
        record = message.record
        if record["level"].name == "ERROR":
            accumulated_errors.append(record["message"])
            # Log at INFO level instead to indicate we caught it
            sys.stderr.write(f"CAUGHT ERROR LOG: {record['message'].splitlines()[0][:100]}\n")
        else:
            # Pass through non-error messages
            sys.stderr.write(str(message))

    # Add our sink
    handler_id = logger.add(error_catching_sink, format="{message}", level="DEBUG")
    # Remove the default stderr handler to prevent duplicate logging
    try:
        logger.remove(0)
    except ValueError:
        pass  # Already removed

    try:
        yield
    finally:
        # Reset the context variable
        _expecting_errors.reset(token)
        # Remove our custom sink
        logger.remove(handler_id)
        # Re-add default stderr handler
        logger.add(sys.stderr, level="DEBUG")
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
                raise IncorrectErrorsLoggedDuringTesting(f"{expected_error=} is not in {accumulated_errors=}")

    return check_func


@contextmanager
def expect_at_least_logged_errors(expected_errors: set[str]) -> Iterator[None]:
    """Context manager that intercepts ERROR logs using loguru's sink system.
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
    """Context manager that intercepts ERROR logs using loguru's sink system.
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


@pytest.fixture
def explode_on_error() -> Generator[None, None, None]:
    """Fixture to explode on error - fails the test if any ERROR logs are recorded.

    This fixture is aware of the expect_*_logged_errors context managers and will
    ignore ERROR logs that occur within those blocks.
    """
    accumulated_errors: list[str] = []

    def error_catching_sink(message: Any) -> None:
        record = message.record
        if record["level"].name == "ERROR":
            # Only accumulate errors if we're NOT expecting them
            if not _expecting_errors.get():
                accumulated_errors.append(record["message"])
        # Always write to stderr
        sys.stderr.write(str(message))

    # Add our sink
    handler_id = logger.add(
        error_catching_sink,
        format="{level} | {name}:{function}:{line} - {message}",
        level="DEBUG",
    )
    # Remove default handler to prevent duplicates
    try:
        logger.remove(0)
    except ValueError:
        pass

    try:
        yield
    except BaseException:
        raise
    else:
        if len(accumulated_errors) > 0:
            raise IncorrectErrorsLoggedDuringTesting(f"Errors logged during testing: {accumulated_errors}")
    finally:
        logger.remove(handler_id)
        # Re-add default handler
        logger.add(sys.stderr, level="DEBUG")


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
        with expect_at_least_logged_errors({"Something bad happened", "Something else bad happened"}):
            logger.error("Something bad happened")
