"""Data types for Codex agent integration."""

from pathlib import Path
from typing import Annotated
from typing import Any
from typing import Literal

from pydantic import Field
from pydantic import Tag

from vet.imbue_core.agents.agent_api.data_types import AgentOptions
from vet.imbue_core.agents.agent_api.data_types import AgentToolName
from vet.imbue_core.pydantic_serialization import SerializableModel
from vet.imbue_core.pydantic_serialization import build_discriminator

# https://developers.openai.com/codex/cli/features#approval-modes
CodexApprovalMode = Literal["auto", "read-only", "full-access"] | None

# https://developers.openai.com/codex/cli/reference, --sandbox options
CodexSandboxMode = Literal["read-only", "workspace-write", "danger-full-access"] | None

# https://developers.openai.com/codex/cli/reference, --ask-for-approval options
CodexApprovalPolicy = Literal["untrusted", "on-failure", "on-request", "never"] | None


class CodexOptions(AgentOptions):
    """Options for Codex CLI execution."""

    object_type: Literal["CodexOptions"] = "CodexOptions"

    approval_mode: CodexApprovalMode = None
    sandbox_mode: CodexSandboxMode = None
    approval_policy: CodexApprovalPolicy = None
    model: str | None = None
    system_prompt: str | None = None
    image_paths: list[Path] = Field(default_factory=list)
    skip_git_repo_check: bool = False
    output_schema: dict[str, Any] | None = None
    # Session management
    resume_session_id: str | None = None
    resume_last: bool = False
    thread_id: str | None = None
    # Optional override for the Codex CLI path
    cli_path: Path | None = None
    is_cached: bool = False


# Codex item types
# Ref: https://github.com/openai/codex/blob/main/sdk/typescript/src/items.ts
# Ref: https://github.com/openai/codex/blob/main/codex-rs/exec/src/exec_events.rs


# The status of a command execution.
CommandExecutionStatus = Literal["in_progress", "completed", "failed"]


class CodexCommandExecutionItem(SerializableModel):
    type: Literal["command_execution"] = "command_execution"
    id: str
    command: str
    aggregated_output: str
    exit_code: int | None = None
    status: CommandExecutionStatus


# Indicates the type of the file change.
PatchChangeKind = Literal["add", "delete", "update"]


class CodexFileUpdateChange(SerializableModel):
    path: str
    kind: PatchChangeKind


# The status of a file change.
PatchApplyStatus = Literal["completed", "failed"]


class CodexFileChangeItem(SerializableModel):
    type: Literal["file_change"] = "file_change"
    id: str
    changes: list[CodexFileUpdateChange]
    status: PatchApplyStatus


# The status of an MCP tool call.
McpToolCallStatus = Literal["in_progress", "completed", "failed"]


class CodexMcpToolCallItem(SerializableModel):
    type: Literal["mcp_tool_call"] = "mcp_tool_call"
    id: str
    server: str
    tool: str
    status: McpToolCallStatus


class CodexAgentMessageItem(SerializableModel):
    type: Literal["agent_message"] = "agent_message"
    id: str
    text: str


class CodexReasoningItem(SerializableModel):
    type: Literal["reasoning"] = "reasoning"
    id: str
    text: str


class CodexWebSearchItem(SerializableModel):
    type: Literal["web_search"] = "web_search"
    id: str
    query: str


class CodexErrorItem(SerializableModel):
    type: Literal["error"] = "error"
    id: str
    message: str


class CodexTodoItem(SerializableModel):
    text: str
    completed: bool


class CodexTodoListItem(SerializableModel):
    type: Literal["todo_list"] = "todo_list"
    id: str
    items: list[CodexTodoItem]


# Canonical union of thread items and their type-specific payloads.
CodexThreadItemUnion = Annotated[
    (
        Annotated[CodexAgentMessageItem, Tag("agent_message")]
        | Annotated[CodexReasoningItem, Tag("reasoning")]
        | Annotated[CodexCommandExecutionItem, Tag("command_execution")]
        | Annotated[CodexFileChangeItem, Tag("file_change")]
        | Annotated[CodexMcpToolCallItem, Tag("mcp_tool_call")]
        | Annotated[CodexWebSearchItem, Tag("web_search")]
        | Annotated[CodexTodoListItem, Tag("todo_list")]
        | Annotated[CodexErrorItem, Tag("error")]
    ),
    build_discriminator("type"),
]


# Codex (JSONL) event stream models
# Ref:https://github.com/openai/codex/blob/main/sdk/typescript/src/events.ts


class CodexThreadStartedEvent(SerializableModel):
    type: Literal["thread.started"] = "thread.started"
    thread_id: str


class CodexTurnStartedEvent(SerializableModel):
    type: Literal["turn.started"] = "turn.started"


class CodexUsage(SerializableModel):
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int


class CodexTurnCompletedEvent(SerializableModel):
    type: Literal["turn.completed"] = "turn.completed"
    usage: CodexUsage


class CodexThreadError(SerializableModel):
    message: str


class CodexTurnFailedEvent(SerializableModel):
    type: Literal["turn.failed"] = "turn.failed"
    error: CodexThreadError


class CodexItemStartedEvent(SerializableModel):
    type: Literal["item.started"] = "item.started"
    item: CodexThreadItemUnion


class CodexItemUpdatedEvent(SerializableModel):
    type: Literal["item.updated"] = "item.updated"
    item: CodexThreadItemUnion


class CodexItemCompletedEvent(SerializableModel):
    type: Literal["item.completed"] = "item.completed"
    item: CodexThreadItemUnion


class CodexThreadErrorEvent(SerializableModel):
    type: Literal["error"] = "error"
    message: str


CodexThreadEvent = Annotated[
    (
        Annotated[CodexThreadStartedEvent, Tag("thread.started")]
        | Annotated[CodexTurnStartedEvent, Tag("turn.started")]
        | Annotated[CodexTurnCompletedEvent, Tag("turn.completed")]
        | Annotated[CodexTurnFailedEvent, Tag("turn.failed")]
        | Annotated[CodexItemStartedEvent, Tag("item.started")]
        | Annotated[CodexItemUpdatedEvent, Tag("item.updated")]
        | Annotated[CodexItemCompletedEvent, Tag("item.completed")]
        | Annotated[CodexThreadErrorEvent, Tag("error")]
    ),
    build_discriminator("type"),
]

# TODO: some of these might not actually be valid for codex!
CODEX_TOOLS = (
    AgentToolName.AGENT,
    AgentToolName.BASH,
    AgentToolName.EDIT,
    AgentToolName.GLOB,
    AgentToolName.GREP,
    AgentToolName.LS,
    AgentToolName.MULTI_EDIT,
    AgentToolName.NOTEBOOK_EDIT,
    AgentToolName.NOTEBOOK_READ,
    AgentToolName.READ,
    AgentToolName.TODO_READ,
    AgentToolName.TODO_WRITE,
    AgentToolName.WEB_FETCH,
    AgentToolName.WEB_SEARCH,
    AgentToolName.WRITE,
    AgentToolName.COMPUTER,
    AgentToolName.MEMORY,
    AgentToolName.OTHER,
    AgentToolName.CODE_EXECUTION,
    AgentToolName.BASH_CODE_EXECUTION,
    AgentToolName.TEXT_EDITOR_CODE_EXECUTION,
    AgentToolName.COMMAND_EXECUTION,
    AgentToolName.FILE_CHANGE,
)
