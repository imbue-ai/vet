import subprocess
from pathlib import Path
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


class GitCommandError(GitException):
    """Structured git error handler for consistent error reporting.

    Translates RunCommandError into user-friendly messages with context
    about what operation failed and why.
    """

    def __init__(self, error: RunCommandError, operation: str, repo_path: Path):
        """Initialize with error context.

        Args:
            error: The underlying RunCommandError
            operation: Human-readable description of what was being attempted
            repo_path: Path to the repository
        """
        self.error = error
        self.operation = operation
        self.repo_path = repo_path
        super().__init__(self.user_message())

    def user_message(self) -> str:
        """Generate a user-friendly error message with full context."""
        stderr = self.error.stderr or ""

        # Build the message with context
        lines = [
            f"Git operation failed: {self.operation}",
            f"Repository: {self.repo_path}",
            f"Command: {self.error.cmd}",
            "",
        ]

        # Extract the core error message
        if stderr.strip():
            # Get just the error line, not the full traceback
            error_lines = stderr.strip().split("\n")
            error_msg = error_lines[-1]  # Usually the most relevant line is last
            lines.append(f"Error: {error_msg}")
        else:
            lines.append(f"Exit code: {self.error.returncode}")

        # Add helpful troubleshooting hints based on the error
        lines.append("")
        lines.extend(self._get_troubleshooting_hints(stderr))

        return "\n".join(lines)

    def _get_troubleshooting_hints(self, stderr: str) -> list[str]:
        """Generate troubleshooting hints based on the error message."""
        hints = []

        # Common git errors
        if "not a git repository" in stderr:
            hints.append("Troubleshooting:")
            hints.append("  • Ensure the repository path points to a valid git repository")
            hints.append("  • Check that .git directory exists in the repository")

        elif "no such ref" in stderr.lower() or "does not point to a valid object" in stderr.lower():
            hints.append("Troubleshooting:")
            hints.append("  • The repository may have no commits yet")
            hints.append("  • Try making an initial commit before running vet")

        elif "bad revision" in stderr.lower() or "unknown revision" in stderr.lower():
            hints.append("Troubleshooting:")
            hints.append("  • The specified git ref/branch may not exist")
            hints.append("  • Verify the branch or commit hash is correct")

        elif "permission denied" in stderr.lower():
            hints.append("Troubleshooting:")
            hints.append("  • Check file permissions on the repository")
            hints.append("  • Ensure you have read/write access to the .git directory")

        else:
            # Generic fallback hints
            hints.append("Troubleshooting:")
            hints.append("  • Check your git configuration and repository state")
            hints.append("  • Run 'git status' to diagnose repository issues")

        return hints
