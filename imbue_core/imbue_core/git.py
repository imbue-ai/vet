"""Utility abstractions for interacting with git repositories."""

from __future__ import annotations

import asyncio
import shlex
import subprocess
import sys
from asyncio.subprocess import PIPE
from asyncio.subprocess import STDOUT
from io import StringIO
from pathlib import Path
from typing import Any
from typing import Sequence
from typing import TextIO


def is_path_in_git_repo(path: Path) -> bool:
    """Check if a path is in a git repository."""
    if path.is_file():
        path = path.parent
    completed_process = subprocess.run(
        ["git", "-C", path, "rev-parse", "--is-inside-work-tree"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed_process.returncode != 0:
        return False
    result = completed_process.stdout.decode().strip()
    assert result in ("true", "false"), result
    return result == "true"


def get_git_repo_root() -> Path:
    """Gets a Path to the current git repo root, assuming that our cwd is somewhere inside the repo."""
    completed_process = subprocess.run(
        ("git", "rev-parse", "--show-toplevel"),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    root_dir = Path(completed_process.stdout.decode().strip())
    assert root_dir.is_dir(), f"{root_dir} must be a directory"
    return root_dir


def get_git_repo_root_from_path(path: Path) -> Path:
    """Gets a Path to the git repo root for the given path."""
    if path.is_file():
        path = path.parent
    completed_process = subprocess.run(
        ["git", "-C", path, "rev-parse", "--show-toplevel"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    root_dir = Path(completed_process.stdout.decode().strip())
    assert root_dir.is_dir(), f"{root_dir} must be a directory"
    return root_dir


def get_repo_url_from_folder(repo_path: Path) -> str:
    try:
        repo_url = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            cwd=repo_path,
            universal_newlines=True,
        ).strip()
    except subprocess.CalledProcessError:
        raise
    else:
        if repo_url.startswith("git@"):
            # convert ssh url to https
            repo_url = repo_url.replace(":", "/")
            repo_url = f"https://{repo_url[4:]}"
        if "https://oauth2:" in repo_url:
            # remove the oauth2 prefix
            # repo_url is something like https://oauth2:{token}@gitlab.com/.../.git
            # change it to https://gitlab.com/.../.git
            # This will happen if repo was originallycloned using oauth2
            suffix = repo_url.split("@")[-1]
            repo_url = "https://" + suffix
        return repo_url


def get_repo_base_path() -> Path:
    working_directory = Path(__file__).parent
    try:
        return Path(
            _run_command_and_capture_output(
                ["git", "rev-parse", "--show-toplevel"], cwd=working_directory
            ).strip()
        )
    except subprocess.CalledProcessError as e:
        try:
            return working_directory.parents[1]
        except IndexError:
            raise UnableToFindRepoBase() from e


def _run_command_and_capture_output(
    args: Sequence[str], cwd: Path | None = None
) -> str:
    arg_str = " ".join(shlex.quote(arg) for arg in args)
    print(f"Running command: {arg_str}", file=sys.stderr)
    with subprocess.Popen(
        args, text=True, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    ) as proc:
        with StringIO() as output:
            _handle_output(proc, output, sys.stderr)
            if proc.wait() != 0:
                raise subprocess.CalledProcessError(
                    proc.returncode, cmd=args, output=output.getvalue()
                )
            return output.getvalue()


class UnableToFindRepoBase(Exception):
    """Raised when the base of the repository cannot be found."""


def _handle_output(process: subprocess.Popen[str], *files: TextIO) -> None:
    process_stdout = process.stdout
    assert process_stdout is not None
    while True:
        output = process_stdout.read(1)
        if output:
            for f in files:
                f.write(output)
        elif process.poll() is not None:
            break


def get_diff_without_index(diff: str) -> str:
    new_lines = []
    for line in diff.splitlines():
        if line.startswith("index "):
            # We replace index lines with "index 0000000..0000000 100644" because:
            # - `0000000..0000000` ensures no real object hashes are referenced, making the diff neutral.
            # - `100644` is the standard file mode for non-executable files in git diffs, ensuring compatibility.
            # - This keeps the diff format valid while removing specific index information.
            new_lines.append("index 0000000..0000000 100644")
        else:
            new_lines.append(line)
    return "\n".join(new_lines).strip()


def is_diffs_without_index_equal(diff_1: str, diff_2: str) -> bool:
    return get_diff_without_index(diff_1) == get_diff_without_index(diff_2)


# Utility function for running shell commands and collecting output.
async def get_lines_from_process(
    shell_command: str, is_exit_code_validated: bool = True, **kwargs: Any
) -> list[str]:
    p = await asyncio.create_subprocess_shell(
        shell_command, stdin=PIPE, stdout=PIPE, stderr=STDOUT, **kwargs
    )
    lines = [x.decode("UTF-8") for x in (await p.communicate())[0].splitlines()]
    if is_exit_code_validated:
        joined_lines = "\n".join(lines)
        assert p.returncode == 0, (
            f"command failed: {shell_command}\nwith output:\n{joined_lines} with exit code {p.returncode}"
        )
    return lines
