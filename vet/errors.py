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


class IssueResponseParsingError(Exception):
    """An issue-identification response could not be parsed into the issue schema, even after a retry.

    Raised instead of silently treating the response as "no issues": a prose verdict that fails to
    parse may contain real findings, so it must surface as a hard failure with the raw text attached.
    """

    def __init__(self, phase: str, reason: str, raw_responses: tuple[str, ...]) -> None:
        self.phase = phase
        self.reason = reason
        self.raw_responses = raw_responses
        attempts = len(raw_responses)
        summary = (
            f"{phase}: model response could not be parsed as issue JSON after {attempts} attempt"
            f"{'s' if attempts != 1 else ''} ({reason}). "
            "Treating this as zero findings would be a false pass, so the run is aborted."
        )
        super().__init__(summary)

    def __str__(self) -> str:
        parts = [self.args[0]]
        for index, raw_response in enumerate(self.raw_responses, start=1):
            parts.append(f"--- raw response (attempt {index}) ---\n{raw_response.rstrip()}\n--- end raw response ---")
        return "\n".join(parts)
