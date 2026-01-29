"""Error types for Agent API."""

from typing import Any


class AgentAPIError(Exception):
    """Base exception for all Agent API errors."""


class AgentCLIConnectionError(AgentAPIError):
    """Raised when unable to connect to Agent Code."""


class AgentCLINotFoundError(AgentCLIConnectionError):
    """Raised when Agent Code is not found or not installed."""

    def __init__(self, message: str, cli_path: str | None = None) -> None:
        if cli_path:
            message = f"{message}: {cli_path}"
        super().__init__(message)


class AgentProcessError(AgentAPIError):
    """Raised when the CLI process fails."""

    def __init__(self, message: str, exit_code: int | None = None, stderr: str | None = None) -> None:
        self.exit_code = exit_code
        self.stderr = stderr

        if exit_code is not None:
            message = f"{message} (exit code: {exit_code})"
        if stderr:
            message = f"{message}\nError output: {stderr}"

        super().__init__(message)


class AgentCLIJSONDecodeError(AgentAPIError):
    """Raised when unable to decode JSON from CLI output."""

    def __init__(self, line: str, original_error: Exception) -> None:
        self.line = line
        self.original_error = original_error
        super().__init__(f"Failed to decode JSON: {line[:100]}...")


class AgentUnknownMessageTypeError(AgentAPIError):
    """Raised when an unknown message type is encountered."""

    def __init__(self, message_type: str, data: dict[str, Any]) -> None:
        self.message_type = message_type
        self.data = data
        super().__init__(f"Unknown message type: {message_type}\nData: {data}")


class AgentUnknownContentBlockTypeError(AgentAPIError):
    """Raised when an unknown content block type is encountered."""

    def __init__(self, block_type: str, data: dict[str, Any]) -> None:
        self.block_type = block_type
        self.data = data
        super().__init__(f"Unknown content block type: {block_type}\nData: {data}")
