import contextlib
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Generator
from typing import Iterator

import pytest


@contextlib.contextmanager
def create_temp_file(contents: str, suffix: str, root_dir: Path) -> Generator[Path, None, None]:
    with NamedTemporaryFile(mode="w", suffix=suffix, dir=root_dir, delete=False) as temp_file:
        temp_file.write(contents)
        temp_file.flush()
        yield Path(temp_file.name)
        temp_file.close()
        Path(temp_file.name).unlink()


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
