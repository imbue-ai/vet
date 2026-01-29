import contextlib
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Generator
from typing import Iterator

import pytest

from imbue_core.log_utils import ensure_core_log_levels_configured
from imbue_core.test_repo_utils import make_test_data_mock_repo


@pytest.fixture(scope="session", autouse=True)
def setup_logging_and_secrets() -> None:
    ensure_core_log_levels_configured()


@contextlib.contextmanager
def create_temp_file(contents: str, suffix: str, root_dir: Path) -> Generator[Path, None, None]:
    with NamedTemporaryFile(mode="w", suffix=suffix, dir=root_dir, delete=False) as temp_file:
        temp_file.write(contents)
        temp_file.flush()
        yield Path(temp_file.name)
        temp_file.close()
        Path(temp_file.name).unlink()


mock_repo = pytest.fixture(make_test_data_mock_repo)


@contextlib.contextmanager
def dummy_exception_manager() -> Iterator[None]:
    """
    Use with patch to disable exception managing for LLM calls.
    Useful when you want a test to fail fast.

    Example:
    with patch("imbue_core.agents.llm_apis.anthropic_api._anthropic_exception_manager", dummy_exception_manager):
        # your test code here
    """
    yield
