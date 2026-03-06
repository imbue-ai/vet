from pathlib import Path

from vet.errors import GitCommandError
from vet.errors import GitException
from vet.errors import RunCommandError
from vet.git import SyncLocalGitRepo
from vet.git import find_relative_to_commit_hash
from vet.imbue_core.async_monkey_patches import log_exception

# Maximum length of LLM prompts used within vet in tokens, without the repository-specific context.
# Currently, the prompt is well under 10k tokens, but this value might need to be bumped up if we add a lot of additional
# identification guides, few-shot examples, or other context.
VET_MAX_PROMPT_TOKENS = 10000


def get_code_to_check(relative_to: str, repo_path: Path, only_staged: bool = False) -> tuple[str, str, str]:
    """
    Returns:
    - The commit hash to use as the base commit for the diff. When `only_staged` is True
      this will be the current HEAD (staged-only mode ignores `relative_to`).
    - The combined diff. When `only_staged` is False this includes staged, unstaged,
      and untracked changes (compatible with `git apply`). When `only_staged` is True
      this includes only staged changes.
    - The combined diff with binary diffs shortened (cannot be applied if binary
      changes are present). When `only_staged` is True this is generated from staged
      changes only.
    Note: When `only_staged` is True the `relative_to` argument is ignored; staged-only
    analysis does not attempt to resolve or use the configured base commit.
    """
    repo = SyncLocalGitRepo(repo_path)

    if only_staged:
        # In staged mode we ignore `relative_to` entirely. Avoid resolving the
        # configured base commit since it may refer to a branch/ref that doesn't
        # exist in the current working copy (e.g., config sets `main`). This
        # prevents unnecessary git errors when the user explicitly requested
        # staged-only analysis.
        try:
            combined_diff = repo.get_git_diff(only_staged=True)
            combined_diff_no_binary = repo.get_git_diff(only_staged=True, include_binary=False)
            # No untracked files in staged mode. Use HEAD as the base commit for
            # consistency with non-staged behavior.
            base_commit = repo.run_git(["rev-parse", "HEAD"])
        except RunCommandError as e:
            # If either obtaining the staged diff or resolving HEAD fails,
            # surface a wrapped GitCommandError so callers receive uniform
            # error information.
            raise GitCommandError(e, "get staged diff or determine HEAD commit", repo_path) from e

        return base_commit, combined_diff, combined_diff_no_binary

    try:
        base_commit = find_relative_to_commit_hash(relative_to, repo_path=repo_path)
    except RunCommandError as e:
        raise GitCommandError(
            e,
            "determine base commit for verification",
            repo_path,
        ) from e

    # Get the combined diff which includes all changes; staged, unstaged, and untracked.
    try:
        combined_diff = repo.get_git_diff(commit_hash=base_commit)
        combined_diff_no_binary = repo.get_git_diff(commit_hash=base_commit, include_binary=False)
    except RunCommandError as e:
        raise GitCommandError(
            e,
            f"get diff since commit {base_commit}",
            repo_path,
        ) from e

    # Get untracked files since we want to include these as part of the unstaged and full changes
    try:
        untracked_files = repo.get_untracked_files()
    except RunCommandError as e:
        raise GitCommandError(e, "list untracked files", repo_path) from e

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
