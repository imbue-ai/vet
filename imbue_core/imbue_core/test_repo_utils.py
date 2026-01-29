"""Utilities for tests involving a git repository."""

import subprocess
import tempfile
from pathlib import Path
from typing import Generator


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
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True)

        # Create initial commit
        (repo_path / "file1.txt").write_text("initial content")
        subprocess.run(["git", "add", "file1.txt"], cwd=repo_path, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_path, check=True)
        (repo_path / "file2.txt").write_text("initial content file 2")
        subprocess.run(["git", "add", "file2.txt"], cwd=repo_path, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit file2"], cwd=repo_path, check=True)

        yield repo_path
