import enum
from pathlib import Path
from typing import Annotated
from typing import Any
from typing import Literal

from pydantic import Field
from pydantic import Tag

from vet.imbue_core.pydantic_serialization import SerializableModel
from vet.imbue_core.pydantic_serialization import build_discriminator

AgentPermissionMode = Literal["default", "acceptEdits", "bypassPermissions"]


class AgentToolName(enum.StrEnum):
    """Enumeration of all known coding agent tools across Claude Code and Codex.

    This is a superset of tools available across different coding agents.
    Not all tools are available in all agents.
    """

    # File operations
    READ = "Read"
    WRITE = "Write"
    EDIT = "Edit"
    MULTI_EDIT = "MultiEdit"
    GLOB = "Glob"
    NOTEBOOK_READ = "NotebookRead"
    NOTEBOOK_EDIT = "NotebookEdit"
    LS = "LS"

    # Search operations
    GREP = "Grep"

    # Execution tools
    BASH = "Bash"
    BASH_OUTPUT = "BashOutput"
    KILL_SHELL = "KillShell"

    # Web operations
    WEB_SEARCH = "WebSearch"
    WEB_FETCH = "WebFetch"

    # Agent orchestration
    TASK = "Task"
    TODO_READ = "TodoRead"
    TODO_WRITE = "TodoWrite"
    SLASH_COMMAND = "SlashCommand"
    EXIT_PLAN_MODE = "exit_plan_mode"

    # MCP tools
    MCP_TOOL = "mcp_tool"  # Generic MCP tool prefix
    LIST_MCP_RESOURCES = "ListMcpResourcesTool"
    READ_MCP_RESOURCE = "ReadMcpResourceTool"

    # Code execution
    CODE_EXECUTION = "code_execution"
    BASH_CODE_EXECUTION = "bash_code_execution"
    TEXT_EDITOR_CODE_EXECUTION = "text_editor_code_execution"

    # Codex-specific operations
    COMMAND_EXECUTION = "command_execution"  # Codex's command execution
    FILE_CHANGE = "file_change"  # Codex's file change operation

    # Other tools
    AGENT = "Agent"
    COMPUTER = "computer"  # Computer use capability
    MEMORY = "memory"  # Memory storage
    OTHER = "other"  # Catch-all for unknown/custom tools


# TODO: these are not, in the strict sense, read-only; perhaps we should have finer gradations
READ_ONLY_TOOLS = (
    AgentToolName.TASK,
    AgentToolName.READ,
    AgentToolName.GLOB,
    AgentToolName.GREP,
    AgentToolName.LS,
    AgentToolName.BASH,
    AgentToolName.NOTEBOOK_READ,
    AgentToolName.TODO_READ,
    AgentToolName.TODO_WRITE,
    AgentToolName.WEB_FETCH,
    AgentToolName.WEB_SEARCH,
)


# Content block types
class AgentTextBlock(SerializableModel):
    """Text content block.

    Represents plain text output from the agent.
    """

    text: str


class AgentThinkingBlock(SerializableModel):
    """Agent's internal reasoning/thinking block.

    Represents the agent's thought process or reasoning, which may be hidden
    from the end user in some interfaces.
    """

    content: str
    thinking_tokens: int | None = Field(default=None, description="Number of tokens used for thinking")


class AgentToolUseBlock(SerializableModel):
    """Tool invocation request.

    Represents a request from the agent to use a specific tool.
    """

    id: str
    name: AgentToolName | str  # allow str for flexibility
    input: dict[str, Any]


class AgentToolResultBlock(SerializableModel):
    """Tool execution result.

    Represents the result of executing a tool, which is fed back to the agent.
    """

    tool_use_id: str
    content: str | list[dict[str, Any]] | None = None
    is_error: bool | None = None
    exit_code: int | None = Field(default=None, description="Exit code for command executions")


AgentContentBlock = AgentTextBlock | AgentThinkingBlock | AgentToolUseBlock | AgentToolResultBlock


class AgentSystemEventType(enum.StrEnum):
    """System event types

    Super set of system event types across all agents.
    """

    SESSION_STARTED = "session_started"
    SESSION_RESUMED = "session_resumed"
    TURN_STARTED = "turn_started"
    TURN_COMPLETED = "turn_completed"
    TURN_FAILED = "turn_failed"
    # For agent-specific events that don't fit into the above categories
    OTHER = "other"


# Message types (`type` field is required for serialization)
class AgentUserMessage(SerializableModel):
    """User message.

    Represents input from the user to the agent.
    """

    object_type: Literal["AgentUserMessage"] = "AgentUserMessage"
    content: str | list[AgentContentBlock]
    original_message: dict[str, Any] | None = Field(default=None, description="Original agent-specific message data")


class AgentAssistantMessage(SerializableModel):
    """Assistant message with content blocks.

    Represents output from the agent, which may include text, thinking,
    tool uses, and tool results.
    """

    object_type: Literal["AgentAssistantMessage"] = "AgentAssistantMessage"
    content: list[AgentContentBlock]
    original_message: dict[str, Any] | None = Field(default=None, description="Original agent-specific message data")


class AgentSystemMessage(SerializableModel):
    """System message with normalized event data.

    Represents lifecycle events from the agent session (e.g., turn started,
    turn completed, session started).
    """

    object_type: Literal["AgentSystemMessage"] = "AgentSystemMessage"
    event_type: AgentSystemEventType
    session_id: str | None = Field(default=None, description="Session/thread identifier")
    error: str | None = Field(default=None, description="Error message for failed events")
    original_message: dict[str, Any] | None = Field(default=None, description="Original agent-specific message data")


class AgentUsage(SerializableModel):
    """Normalized usage tracking across agents.

    Tracks token usage and costs in a unified format.
    """

    input_tokens: int | None = Field(default=None, description="Input/prompt tokens consumed")
    output_tokens: int | None = Field(default=None, description="Output/completion tokens generated")
    cached_tokens: int | None = Field(default=None, description="Cached input tokens reused")
    total_tokens: int | None = Field(default=None, description="Total tokens (input + output)")
    thinking_tokens: int | None = Field(default=None, description="Tokens used for extended thinking")
    total_cost_usd: float | None = Field(default=None, description="Estimated cost in USD")


class AgentResultMessage(SerializableModel):
    """Result message with cost and usage information.

    Represents the final result of an agent session, including timing,
    usage statistics, and success/error status.
    """

    object_type: Literal["AgentResultMessage"] = "AgentResultMessage"
    session_id: str
    is_error: bool
    duration_ms: int | None = Field(default=None, description="Total duration in milliseconds")
    api_duration_ms: int | None = Field(default=None, description="API call duration in milliseconds")
    num_turns: int | None = Field(default=None, description="Number of conversation turns")
    usage: AgentUsage | None = Field(default=None, description="Token usage and cost information")
    result: str | None = Field(default=None, description="Final result or output from the agent")
    error: str | None = Field(default=None, description="Error message if is_error=True")
    original_message: dict[str, Any] | None = Field(default=None, description="Original agent-specific message data")


AgentMessage = AgentUserMessage | AgentAssistantMessage | AgentSystemMessage | AgentResultMessage
AgentMessageUnion = Annotated[
    Annotated[AgentUserMessage, Tag("AgentUserMessage")]
    | Annotated[AgentAssistantMessage, Tag("AgentAssistantMessage")]
    | Annotated[AgentSystemMessage, Tag("AgentSystemMessage")]
    | Annotated[AgentResultMessage, Tag("AgentResultMessage")],
    build_discriminator(),
]


class ToolUseRecord(SerializableModel):
    """A record of a tool use."""

    request_message: AgentToolUseBlock
    result_message: AgentToolResultBlock

    @property
    def tool_name(self) -> str:
        """The name of the tool used."""
        return self.request_message.name

    @property
    def tool_input(self) -> dict[str, Any]:
        """The input to the tool."""
        return self.request_message.input


class AgentOptions(SerializableModel):
    """Parent class for all agent options."""

    cwd: str | Path | None = None
