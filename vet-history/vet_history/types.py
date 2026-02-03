"""VET-compatible output types for conversation history.

These types match the format expected by VET's parse_conversation_history() function.
The output is JSONL where each line is either a ChatInputUserMessage or ResponseBlockAgentMessage.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Annotated
from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


def generate_id() -> str:
    """Generate a unique ID."""
    return str(uuid.uuid4())


def get_current_time() -> datetime.datetime:
    """Get current UTC time."""
    return datetime.datetime.now(datetime.timezone.utc)


# =============================================================================
# Content Blocks (for ResponseBlockAgentMessage)
# =============================================================================


class TextBlock(BaseModel):
    """Text content block."""

    model_config = ConfigDict(extra="forbid")

    object_type: Literal["TextBlock"] = "TextBlock"
    type: Literal["text"] = "text"
    text: str


class ToolUseBlock(BaseModel):
    """Tool invocation block."""

    model_config = ConfigDict(extra="forbid")

    object_type: Literal["ToolUseBlock"] = "ToolUseBlock"
    type: Literal["tool_use"] = "tool_use"
    id: str = Field(default_factory=generate_id)
    name: str
    input: dict[str, Any] = Field(default_factory=dict)


class GenericToolContent(BaseModel):
    """Generic tool result content."""

    model_config = ConfigDict(extra="forbid")

    content_type: Literal["generic"] = "generic"
    text: str


class DiffToolContent(BaseModel):
    """Diff tool result content for file modifications."""

    model_config = ConfigDict(extra="forbid")

    content_type: Literal["diff"] = "diff"
    diff: str
    file_path: str


ToolResultContentType = GenericToolContent | DiffToolContent


class ToolResultBlock(BaseModel):
    """Tool execution result block."""

    model_config = ConfigDict(extra="forbid")

    object_type: Literal["ToolResultBlock"] = "ToolResultBlock"
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    tool_name: str
    invocation_string: str = ""
    content: ToolResultContentType
    is_error: bool = False


class ErrorBlock(BaseModel):
    """Error content block."""

    model_config = ConfigDict(extra="forbid")

    object_type: Literal["ErrorBlock"] = "ErrorBlock"
    type: Literal["error"] = "error"
    message: str
    traceback: str = ""
    error_type: str = "Error"


class WarningBlock(BaseModel):
    """Warning content block."""

    model_config = ConfigDict(extra="forbid")

    object_type: Literal["WarningBlock"] = "WarningBlock"
    type: Literal["warning"] = "warning"
    message: str
    traceback: str | None = None
    warning_type: str | None = None


# Union of all content block types
ContentBlockType = Annotated[
    TextBlock | ToolUseBlock | ToolResultBlock | ErrorBlock | WarningBlock,
    Field(discriminator="type"),
]


# =============================================================================
# Message Types
# =============================================================================


class ChatInputUserMessage(BaseModel):
    """User input message.

    This represents a message from the user to the agent.
    """

    model_config = ConfigDict(extra="forbid")

    object_type: Literal["ChatInputUserMessage"] = "ChatInputUserMessage"
    message_id: str = Field(default_factory=generate_id)
    source: Literal["USER"] = "USER"
    approximate_creation_time: datetime.datetime = Field(default_factory=get_current_time)
    text: str
    model_name: str | None = None
    files: list[str] = Field(default_factory=list)


class ResponseBlockAgentMessage(BaseModel):
    """Agent response message.

    This represents a message from the agent, which can contain multiple content blocks
    including text, tool uses, and tool results.
    """

    model_config = ConfigDict(extra="forbid")

    object_type: Literal["ResponseBlockAgentMessage"] = "ResponseBlockAgentMessage"
    message_id: str = Field(default_factory=generate_id)
    source: Literal["AGENT"] = "AGENT"
    approximate_creation_time: datetime.datetime = Field(default_factory=get_current_time)
    role: Literal["user", "assistant", "system"]
    assistant_message_id: str = Field(default_factory=generate_id)
    content: tuple[ContentBlockType, ...]


# Union of all message types for JSONL output
ConversationMessage = ChatInputUserMessage | ResponseBlockAgentMessage


# =============================================================================
# Session Metadata
# =============================================================================


class SessionInfo(BaseModel):
    """Information about a session."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    project_path: str | None = None
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None
    title: str | None = None
    agent: str  # "claude-code", "opencode", "codex"


# =============================================================================
# Utility Functions
# =============================================================================


def message_to_jsonl(message: ConversationMessage) -> str:
    """Convert a message to a JSONL line."""
    return message.model_dump_json()


def messages_to_jsonl(messages: list[ConversationMessage]) -> str:
    """Convert a list of messages to JSONL format."""
    return "\n".join(message_to_jsonl(msg) for msg in messages)
