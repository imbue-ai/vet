import subprocess
from typing import Any


class GitException(Exception):
    pass


class RunCommandError(subprocess.CalledProcessError):
    """Custom exception for errors encountered during shell commands."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.cwd = kwargs.get("cwd", None)
        if "cwd" in kwargs:
            del kwargs["cwd"]
        super().__init__(*args, **kwargs)

    def __str__(self) -> str:
        return f"Command `{self.cmd}` returned non-zero exit status {self.returncode}.\nOutput: {self.stdout}\nError: {self.stderr}\nCWD: {self.cwd}"
