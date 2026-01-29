from pathlib import Path

from imbue_core.async_monkey_patches import log_exception
from imbue_core.computing_environment.data_types import RunCommandError
from imbue_core.simple_git import SyncLocalGitRepo
from imbue_tools.repo_utils.find_relative_to import find_relative_to_commit_hash
from imbue_verify.errors import GitException

# Maximum length of LLM prompts used within imbue_verify in tokens, without the repository-specific context.
# Currently, the prompt is well under 10k tokens, but this value might need to be bumped up if we add a lot of additional
# identification guides, few-shot examples, or other context.
IMBUE_VERIFY_MAX_PROMPT_TOKENS = 10000


def get_code_to_check(relative_to: str, repo_path: Path) -> tuple[str, str, str]:
    """
    Returns:
    - The commit hash to use as the base commit for the diff.
    - The combined diff including staged, unstaged, and untracked changes. (compatible with `git apply`)
    - The combined diff but with binary diffs shortened. (cannot be applied if binary changes are present)
    """
    try:
        base_commit = find_relative_to_commit_hash(relative_to, repo_path=repo_path)
    except RunCommandError as e:
        raise GitException(f"Unable to determine base commit for code verification: {e}") from e

    repo = SyncLocalGitRepo(repo_path)

    # Get the combined diff which includes all changes; staged, unstaged, and untracked.
    try:
        combined_diff = repo.get_git_diff(commit_hash=base_commit)
        combined_diff_no_binary = repo.get_git_diff(commit_hash=base_commit, include_binary=False)
    except RunCommandError as e:
        raise GitException(f"Unable to get diff to {base_commit}: {e}") from e

    # Get untracked files since we want to include these as part of the unstaged and full changes
    try:
        untracked_files = repo.get_untracked_files()
    except RunCommandError as e:
        raise GitException(f"Unable to get untracked files: {e}") from e

    # Create diffs for untracked files (treat them as new files)
    untracked_diffs = []
    untracked_diffs_no_binary = []
    for file_path in untracked_files:
        if file_path:  # Skip empty lines
            try:
                untracked_diff = repo.get_untracked_file_diff(file_path, include_binary=True)
                untracked_diffs.append(untracked_diff)
            except RunCommandError as e:
                log_exception(
                    e,
                    "Skipping untracked file we couldn't diff: {file_path}",
                    file_path=file_path,
                )

            try:
                untracked_diff_no_binary = repo.get_untracked_file_diff(file_path, include_binary=False)
                untracked_diffs_no_binary.append(untracked_diff_no_binary)
            except RunCommandError as e:
                log_exception(
                    e,
                    "Skipping untracked file we couldn't diff (no binary): {file_path}",
                    file_path=file_path,
                )

    # Add untracked files to unstaged changes and the combined diff
    if untracked_diffs:
        combined_diff += "\n" + "\n".join(untracked_diffs)
    if untracked_diffs_no_binary:
        combined_diff_no_binary += "\n" + "\n".join(untracked_diffs_no_binary)

    return base_commit, combined_diff, combined_diff_no_binary
