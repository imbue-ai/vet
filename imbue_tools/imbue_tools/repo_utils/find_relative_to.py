from pathlib import Path

from imbue_core.simple_git import SyncLocalGitRepo


def find_relative_to_commit_hash(relative_to: str, repo_path: Path) -> str:
    """
    Find the commit hash to use as the source to compare against.
    - If relative_to is "HEAD", it will return the current commit hash.
    - If relative_to is a branch name, it will find the last common ancestor between that branch and the current state.
    - If relative_to is a commit hash or tag, it will return that commit hash.
    """
    repo = SyncLocalGitRepo(repo_path)
    if relative_to.startswith("HEAD"):
        # The current commit hash or relative to it (e.g. "HEAD~1")
        base_commit = repo.run_git(["rev-parse", relative_to], check=True)
    else:
        # Check if relative_to is the name of a branch.
        is_branch = repo.is_commit_a_branch(relative_to)
        if is_branch:
            # Yes, it's a branch.
            # Since we're comparing to a branch, this command will find the last common ancestor
            # between that branch and the current state. This is typically what we want for branches.
            # (Think of this as getting the diff that would be applied if this branch was to be merged into relative_to.)
            base_commit = repo.get_merge_base(relative_to, "HEAD")
        else:
            # Not a branch. relative_to might be a commit hash or tag.
            base_commit = relative_to

    return base_commit
