"""This file implements a subset of the functionality found in git.py and compute_environment.py, but everything is synchronous."""

import shlex
import subprocess
import time
from pathlib import Path
from typing import Sequence

from loguru import logger

from imbue_core.async_monkey_patches import log_exception
from imbue_core.computing_environment.data_types import AnyPath
from imbue_core.computing_environment.data_types import RunCommandError


class SyncLocalGitRepo:
    """
    Provides different operations that you can perform over a git repository.

    Implements a subset of our async LocalGitRepo, but also pulls in some of the functions from computing_environment.py
    that normally would operate on a LocalGitRepo.

    Over time, we can probably replace LocalGitRepo and computing_environment more or less fully, as we're migrating
    code away from asyncio.

    Feel free to move additional functions from computing_environment.py into this class as needed. Usually, you just need
    to remove async/await keywords, and replace calls to compute_environment. member functions with self. calls.
    """

    _base_path: Path

    def __init__(self, base_path: Path) -> None:
        self._base_path = base_path

    @property
    def base_path(self) -> Path:
        """The base path of the git repo."""
        return self._base_path

    def run_git(
        self,
        command: Sequence[str],
        check: bool = True,
        cwd: AnyPath | None = None,
        is_error_logged: bool = True,
        is_stripped: bool = True,
        retry_on_git_lock_error: bool = True,
    ) -> str:
        """Run a git command in the repo.

        Example:
        ```
        git_repo.run_git("status")
        ```
        """
        command = ["git"] + list(command)
        if not retry_on_git_lock_error:
            result = self.run_command(command, check=check, is_error_logged=is_error_logged, cwd=cwd)
        else:
            result = self._run_command_with_retry_on_git_lock_error(
                command, check=check, is_error_logged=is_error_logged, cwd=cwd
            )
        if is_stripped:
            return result.strip()
        return result

    def run_command(
        self,
        command: Sequence[str],
        check: bool = True,
        secrets: dict[str, str] | None = None,
        cwd: AnyPath | None = None,
        is_error_logged: bool = True,
    ) -> str:
        """Run a command in the repo.

        Note, this can be used to run any command, not just git.
        """
        command_string = shlex.join(command)
        logger.trace(
            f"Running command: {command_string=} from cwd={cwd or self.base_path} with {secrets=} {check=} {is_error_logged=}"
        )
        completed_proc = subprocess.run(
            command,
            cwd=cwd or self._base_path,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=secrets,
        )
        # note, need to be carefull not to strip() lines since whitespace may be important (e.g. for diffs)
        # return joined lines since mostly we only use the output for logging, and this way we arn't
        # passing around lots of lists. Also it's easy to parse by lines if needed
        try:
            stdout = completed_proc.stdout.decode("UTF-8")
        except UnicodeDecodeError as e:
            # If we don't encounter this, it likely means something was fixed upstream and we can safely delete
            log_exception(
                e,
                "Command {command_string} failed to decode stdout, replacing any invalid bytes which could lead to problems later",
                command_string=command_string,
            )
            stdout = completed_proc.stdout.decode("UTF-8", errors="replace")
        stderr = completed_proc.stderr.decode("UTF-8")
        if check and completed_proc.returncode != 0:
            error_message = f"command run from cwd={self.base_path} failed with exit code {completed_proc.returncode} and stdout:\n{stdout}\nstderr:\n{stderr}"
            if is_error_logged:
                logger.error(
                    f"command attempted: '{command_string}' from cwd={self.base_path}\nerror message: {error_message}"
                )
            # this should not be None, but do this to satisfy type checker, int or None we throw the same error
            returncode = completed_proc.returncode or -1
            raise RunCommandError(
                cmd=command_string,
                stderr=stderr,
                returncode=returncode,
                cwd=cwd or self.base_path,
            )
        return stdout

    def get_git_diff(
        self,
        commit_hash: str | None = None,
        staged: bool = False,
        is_error_logged: bool = True,
        include_binary: bool = True,
    ) -> str:
        """Get the diff for the current repo state."""
        # make sure `is_stripped=False` otherwise patch can be invalid
        command = ["diff", "--full-index"]
        if include_binary:
            # Without --binary, diffs of binary files will just contain a summary statement such as "Binary files a/file.bin and b/file.bin differ".
            # Such diffs cannot be applied, but are useful for inclusion in LLM prompts.
            command.append("--binary")
        if staged:
            command.append("--staged")
        if commit_hash:
            command.append(commit_hash)
        return self.run_git(command, is_stripped=False, is_error_logged=is_error_logged)

    def get_untracked_files(self) -> tuple[str, ...]:
        """Get the untracked files in the repo."""
        result = self.run_git(["ls-files", "--others", "--exclude-standard"], is_error_logged=False)
        return tuple([line.strip() for line in result.splitlines() if line.strip()])

    def get_untracked_file_diff(self, file_path: str, include_binary: bool = True) -> str:
        """Get the diff for a untracked file.

        Note this function will raise a RunCommandError if the there is no diff for the untracked file or if there
        is another error running the command. So it is best to use this function after checking that the file is untracked
        using get_untracked_files function.
        """
        command = ["diff", "--no-index"]
        if include_binary:
            command.append("--binary")
        untracked_diff = self.run_git(
            command + ["/dev/null", str(file_path)],
            # Unfortunately, `--no-index` implies `--exit-code`, which will cause git diff to return an exit code of 1
            # if the diff is not empty. So we can't use check=True here. We'll check for an empty output to detect failures.
            check=False,
            is_error_logged=True,
            is_stripped=False,
        )
        if not untracked_diff:
            raise RunCommandError(f"Unable to diff untracked file {file_path}")
        return untracked_diff

    def is_commit_a_branch(self, commit_hash: str) -> bool:
        """Check if the given git ref is a branch."""
        try:
            self.run_git(
                ("show-ref", "--verify", "-q", f"refs/heads/{commit_hash}"),
                is_error_logged=False,
                check=True,
            )
            return True
        except RunCommandError as e:
            if e.returncode == 1:
                return False
            raise

    def get_merge_base(self, branch_name: str, target_branch: str) -> str:
        """Get the merge base of the given branch and target branch.

        The merge base is the most recent commit that is on both branches.
        """
        return self.run_git(["merge-base", branch_name, target_branch], is_error_logged=False)

    def _run_command_with_retry_on_git_lock_error(
        self,
        command: Sequence[str],
        check: bool = True,
        is_error_logged: bool = True,
        cwd: AnyPath | None = None,
    ) -> str:
        max_retries = 50
        retry_count = 0
        retry_delay = 0.1  # seconds
        while True:
            try:
                return self.run_command(
                    command,
                    check=check,
                    is_error_logged=is_error_logged and retry_count >= max_retries,
                    cwd=cwd,
                )
            except RunCommandError as e:
                error_message = str(e)
                if "fatal: Unable to create" in error_message and ".git/index.lock': File exists" in error_message:
                    if retry_count >= max_retries:
                        raise
                    time.sleep(retry_delay)
                    retry_count += 1
                else:
                    raise
