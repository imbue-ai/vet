from typing import Callable
from typing import Generator

import pytest

from imbue_core.async_monkey_patches_test import explode_on_error  # noqa: F401
from imbue_core.log_utils import ensure_core_log_levels_configured
from imbue_core.test_repo_utils import make_simple_test_git_repo

simple_test_git_repo = pytest.fixture(make_simple_test_git_repo)


# this is copied from sculptor/conftest.py
# (it must be copied rather than imported because of the autouse)
@pytest.fixture(autouse=True)
def always_explode_on_error(
    explode_on_error: Callable[[], Generator[None, None, None]],
) -> Generator[None, None, None]:
    """
    Ensures that we do not log errors or exceptions during testing.

    If your test is checking error handling behavior (and you expect to see a log_exception call),
    use the `expect_exact_logged_errors` decorator to suppress the logging of those errors.
    """
    yield


# copied from imbue_core/conftest.py
@pytest.fixture(scope="session", autouse=True)
def setup_logging_and_secrets() -> None:
    ensure_core_log_levels_configured()
