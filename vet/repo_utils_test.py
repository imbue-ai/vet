import subprocess
from pathlib import Path

from syrupy.assertion import SnapshotAssertion

from vet.imbue_core.agents.llm_apis.anthropic_api import AnthropicModelName
from vet.imbue_core.nested_evolver import assign
from vet.imbue_core.nested_evolver import chill
from vet.imbue_core.nested_evolver import evolver
from vet.imbue_tools.repo_utils.project_context import LazyProjectContext
from vet.repo_utils import get_code_to_check


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
