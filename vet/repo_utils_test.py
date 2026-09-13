import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest
from hypothesis import HealthCheck
from hypothesis import given
from hypothesis import settings
from hypothesis import strategies as st
from syrupy.assertion import SnapshotAssertion

from vet.errors import RunCommandError
from vet.git import SyncLocalGitRepo
from vet.imbue_core.agents.llm_apis.anthropic_api import AnthropicModelName
from vet.imbue_core.async_monkey_patches_test import expect_exact_logged_errors
from vet.imbue_core.nested_evolver import assign
from vet.imbue_core.nested_evolver import chill
from vet.imbue_core.nested_evolver import evolver
from vet.imbue_core.test_repo_utils import make_simple_test_git_repo
from vet.imbue_tools.repo_utils.project_context import LazyProjectContext
from vet.repo_utils import get_code_to_check
from vet.repo_utils import strip_submodule_diffs


def test_get_code_to_check(simple_test_git_repo: Path) -> None:
    """Test that get_code_to_check correctly handles staged, unstaged, and untracked files"""
    repo_path = simple_test_git_repo
    first_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # Create an untracked file
    new_file_content = "This is a new untracked file\nwith multiple lines\nof content"
    (repo_path / "new_file.txt").write_text(new_file_content)
    (repo_path / "new_file.bin").write_bytes(b"\x00\x01\x02")

    # Create a committed change
    (repo_path / "file1.txt").write_text("committed modified content\n")
    (repo_path / "file1.bin").write_bytes(b"\x00\x01\x02")
    subprocess.run(["git", "add", "file1.txt"], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-m", "Modify file1"], cwd=repo_path, check=True)

    # Create a staged change
    with open((repo_path / "file1.txt"), "a+") as f:
        # make sure to have multiple newlines to sepearate changes so they don't get
        # picked up in same diff block
        f.write("\nstaged written modified content\n")
    subprocess.run(["git", "add", "file1.txt"], cwd=repo_path, check=True)

    # Create an unstaged change
    with open((repo_path / "file1.txt"), "a+") as f:
        f.write("\nunstaged written modified content")

    git_hash, diff, diff_no_binary = get_code_to_check(first_commit, repo_path=repo_path)

    assert git_hash == first_commit

    # Verify the untracked file is included in the diffs
    assert "new_file.txt" in diff
    assert "new_file.bin" in diff
    assert "new_file.txt" in diff_no_binary
    assert "new_file.bin" in diff_no_binary
    assert "Binary files /dev/null and b/new_file.bin differ" in diff_no_binary

    # Verify tracked changes are also included
    assert "file1.txt" in diff
    assert "+staged written modified content" in diff
    assert "+unstaged written modified content" in diff
    assert "+committed modified content" in diff
    assert "file1.bin" in diff

    assert "file1.txt" in diff_no_binary
    assert "+staged written modified content" in diff_no_binary
    assert "+unstaged written modified content" in diff_no_binary
    assert "+committed modified content" in diff_no_binary
    assert "Binary files /dev/null and b/file1.bin differ" in diff_no_binary


@given(
    link_suffix=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_", min_size=1, max_size=12),
    target_is_directory=st.booleans(),
)
@settings(
    max_examples=20,
    deadline=None,
    # The autouse log fixture is observational; repository state is recreated for every example.
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_get_untracked_file_diff_handles_symlinks(link_suffix: str, target_is_directory: bool) -> None:
    with contextmanager(make_simple_test_git_repo)() as repo_path:
        target_name = "file1.txt"
        if target_is_directory:
            target_name = "target-dir"
            target_dir = repo_path / target_name
            target_dir.mkdir()
            (target_dir / "tracked.txt").write_text("tracked content")
            subprocess.run(["git", "add", target_name], cwd=repo_path, check=True)
            subprocess.run(["git", "commit", "-m", "Add target directory"], cwd=repo_path, check=True)

        link_name = f"link-{link_suffix}"
        (repo_path / link_name).symlink_to(target_name, target_is_directory=target_is_directory)
        repo = SyncLocalGitRepo(repo_path)

        if target_is_directory:
            with pytest.raises(RunCommandError) as exc_info:
                repo.get_untracked_file_diff(link_name)
            assert exc_info.value.returncode == 1
            assert link_name in str(exc_info.value.cmd)
        else:
            diff = repo.get_untracked_file_diff(link_name)
            assert f"diff --git a/{link_name} b/{link_name}" in diff
            assert "new file mode 120000" in diff
            assert f"+{target_name}" in diff


def test_get_code_to_check_skips_untracked_directory_symlink(simple_test_git_repo: Path) -> None:
    target_dir = simple_test_git_repo / "target-dir"
    target_dir.mkdir()
    (target_dir / "untracked.txt").write_text("untracked content")
    (simple_test_git_repo / "link-to-dir").symlink_to("target-dir", target_is_directory=True)

    with expect_exact_logged_errors(
        [
            "Skipping untracked file we couldn't diff: link-to-dir",
            "Skipping untracked file we couldn't diff (no binary): link-to-dir",
        ]
    ):
        _, diff, diff_no_binary = get_code_to_check("HEAD", simple_test_git_repo)

    assert "target-dir/untracked.txt" in diff
    assert "target-dir/untracked.txt" in diff_no_binary
    assert "link-to-dir" not in diff
    assert "link-to-dir" not in diff_no_binary


def test_build_context(simple_test_git_repo: Path, snapshot: SnapshotAssertion) -> None:
    first_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=simple_test_git_repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    git_hash, diff, _diff_no_binary = get_code_to_check(first_commit, repo_path=simple_test_git_repo)
    project_context = LazyProjectContext.build(
        git_hash,
        diff,
        language_model_name=AnthropicModelName.CLAUDE_4_5_HAIKU,
        repo_path=simple_test_git_repo,
        tokens_to_reserve=20000,
    ).to_base_project_context()
    assert project_context.repo_path == simple_test_git_repo

    # the temp dir isn't the same every time so we need to remove it
    project_context_evolver = evolver(project_context)
    assign(
        project_context_evolver.repo_path,
        lambda: None,
    )
    project_context_without_repo_path = chill(project_context_evolver)
    assert project_context_without_repo_path == snapshot


def test_get_code_to_check_staged_only(simple_test_git_repo: Path) -> None:
    """When `only_staged=True`, only staged changes should be returned (no unstaged/untracked),
    and resolving a configured `relative_to` (like 'main') should not error.
    """
    repo_path = simple_test_git_repo

    # Record current HEAD
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # Create an untracked file
    (repo_path / "untracked.txt").write_text("untracked content")

    # Create a staged change
    (repo_path / "file1.txt").write_text("staged content\n")
    subprocess.run(["git", "add", "file1.txt"], cwd=repo_path, check=True)

    # Create an unstaged change
    with open((repo_path / "file1.txt"), "a+") as f:
        f.write("\nunstaged content")

    # Use a relative_to that likely doesn't exist (e.g., 'main') to ensure we don't try to resolve it
    git_hash, diff, diff_no_binary = get_code_to_check("main", repo_path=repo_path, only_staged=True)

    # In staged mode we return HEAD as the base commit
    assert git_hash == head

    # Staged change should be present
    assert "staged content" in diff
    assert "staged content" in diff_no_binary

    # Unstaged and untracked changes should NOT be present
    assert "unstaged content" not in diff
    assert "untracked.txt" not in diff


_REGULAR_FILE_DIFF = """\
diff --git a/src/main.py b/src/main.py
index abc1234..def5678 100644
--- a/src/main.py
+++ b/src/main.py
@@ -1,3 +1,4 @@
 import os
+import sys
 
 def main():
"""

_NEW_SUBMODULE_DIFF = """\
diff --git a/libs/external b/libs/external
new file mode 160000
index 0000000..abc1234
--- /dev/null
+++ b/libs/external
@@ -0,0 +1 @@
+Subproject commit abc1234567890abcdef1234567890abcdef123456
"""

_DELETED_SUBMODULE_DIFF = """\
diff --git a/vendor/old b/vendor/old
deleted file mode 160000
index abc1234..0000000
--- a/vendor/old
+++ /dev/null
@@ -1 +0,0 @@
-Subproject commit abc1234567890abcdef1234567890abcdef123456
"""

_UPDATED_SUBMODULE_DIFF = """\
diff --git a/libs/shared b/libs/shared
index abc1234..def5678 160000
--- a/libs/shared
+++ b/libs/shared
@@ -1 +1 @@
-Subproject commit abc1234567890abcdef1234567890abcdef123456
+Subproject commit def567890abcdef1234567890abcdef1234567890
"""


def test_strip_submodule_diffs_empty() -> None:
    assert strip_submodule_diffs("") == ""


def test_strip_submodule_diffs_no_submodules() -> None:
    assert strip_submodule_diffs(_REGULAR_FILE_DIFF) == _REGULAR_FILE_DIFF


def test_strip_submodule_diffs_removes_new_submodule() -> None:
    combined = _REGULAR_FILE_DIFF + _NEW_SUBMODULE_DIFF
    assert strip_submodule_diffs(combined) == _REGULAR_FILE_DIFF


def test_strip_submodule_diffs_removes_deleted_submodule() -> None:
    combined = _DELETED_SUBMODULE_DIFF + _REGULAR_FILE_DIFF
    assert strip_submodule_diffs(combined) == _REGULAR_FILE_DIFF


def test_strip_submodule_diffs_removes_updated_submodule() -> None:
    combined = _REGULAR_FILE_DIFF + _UPDATED_SUBMODULE_DIFF
    assert strip_submodule_diffs(combined) == _REGULAR_FILE_DIFF


def test_strip_submodule_diffs_only_submodules() -> None:
    combined = _NEW_SUBMODULE_DIFF + _DELETED_SUBMODULE_DIFF + _UPDATED_SUBMODULE_DIFF
    assert strip_submodule_diffs(combined) == ""


def test_strip_submodule_diffs_preserves_files_in_submodule_path() -> None:
    file_in_submodule_dir = """\
diff --git a/libs/external/.gitignore b/libs/external/.gitignore
deleted file mode 100644
index abc1234..0000000
--- a/libs/external/.gitignore
+++ /dev/null
@@ -1,2 +0,0 @@
-target/
-.cache/
"""
    combined = _NEW_SUBMODULE_DIFF + file_in_submodule_dir + _REGULAR_FILE_DIFF
    result = strip_submodule_diffs(combined)
    assert file_in_submodule_dir in result
    assert _REGULAR_FILE_DIFF in result
    assert _NEW_SUBMODULE_DIFF not in result


def test_strip_submodule_diffs_preserves_preamble() -> None:
    preamble = "some preamble text\n"
    combined = preamble + _NEW_SUBMODULE_DIFF + _REGULAR_FILE_DIFF
    result = strip_submodule_diffs(combined)
    assert result == preamble + _REGULAR_FILE_DIFF
