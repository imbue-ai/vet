from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import anyio

# Use AnyPath type to match Sanctum
AnyPath = Path | str | anyio.Path


class RunCommandError(subprocess.CalledProcessError):
    """Custom exception for errors encountered during Git commands."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.cwd = kwargs.get("cwd", None)
        if "cwd" in kwargs:
            del kwargs["cwd"]
        super().__init__(*args, **kwargs)

    def __str__(self) -> str:
        return f"Command `{self.cmd}` returned non-zero exit status {self.returncode}.\nOutput: {self.stdout}\nError: {self.stderr}\nCWD: {self.cwd}"


class PatchApplicationError(Exception):
    """Custom exception for errors encountered during patch application."""


class FailedToMakeCommitError(Exception):
    """Custom exception for errors encountered during commit creation."""
