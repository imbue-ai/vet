"""Utilities for tests involving a git repository."""

import subprocess
import tempfile
from pathlib import Path
from typing import Generator

from imbue_core.common import get_temp_dir
from imbue_core.git import LocalGitRepo
from imbue_core.git import get_git_repo_root
from imbue_core.test_utils import create_temp_dir


def make_simple_test_git_repo() -> Generator[Path, None, None]:
    """Create a temporary git repository for testing.

    Creates a simple repository with two commits and two files.
    - Initial commit with file1.txt
    - Initial commit file2 with file2.txt
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        repo_path = Path(temp_dir)

        # Initialize git repo
        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo_path,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"], cwd=repo_path, check=True
        )

        # Create initial commit
        (repo_path / "file1.txt").write_text("initial content")
        subprocess.run(["git", "add", "file1.txt"], cwd=repo_path, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"], cwd=repo_path, check=True
        )
        (repo_path / "file2.txt").write_text("initial content file 2")
        subprocess.run(["git", "add", "file2.txt"], cwd=repo_path, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit file2"], cwd=repo_path, check=True
        )

        yield repo_path


def make_mock_repo(
    path: Path, is_recreating: bool = False
) -> Generator[LocalGitRepo, None, None]:
    mock_repo = LocalGitRepo(base_path=path)
    with create_temp_dir(root_dir=Path(get_temp_dir())) as temp_dir:
        temp_repo = mock_repo.sync_copy_repo(temp_dir)
        temp_repo.sync_configure_git(
            git_user_name="AGI (Automated Software Inspector)",
            git_user_email="the_true_AGI@running.pytest.com",
            is_recreating=is_recreating,
        )
        yield temp_repo


def make_test_data_mock_repo() -> Generator[LocalGitRepo, None, None]:
    yield from make_mock_repo(
        get_git_repo_root() / "imbue/imbue/test_data/mock_repo", is_recreating=False
    )
