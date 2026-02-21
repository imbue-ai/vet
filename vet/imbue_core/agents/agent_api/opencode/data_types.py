"""Data types for OpenCode agent integration."""

from pathlib import Path
from typing import Any
from typing import Literal

from pydantic import Field

from vet.imbue_core.agents.agent_api.data_types import AgentOptions
from vet.imbue_core.agents.agent_api.data_types import AgentToolName
from vet.imbue_core.pydantic_serialization import SerializableModel


class OpenCodeOptions(AgentOptions):
    """Options for OpenCode CLI execution.

    Reference: `opencode run --help`
    """

    object_type: Literal["OpenCodeOptions"] = "OpenCodeOptions"

    model: str | None = None
    agent: str | None = None
    continue_session: bool = False
    session_id: str | None = None
    fork: bool = False
    dir: str | Path | None = None
    variant: str | None = None
    # Optional override for the OpenCode CLI path
    cli_path: Path | None = None
    is_cached: bool = False


# OpenCode JSON event data types
# Reference: `opencode run --format json`
# Events are JSONL lines with {"type": ..., "timestamp": ..., "sessionID": ..., "part": {...}}


class OpenCodeTokens(SerializableModel):
    """Token usage from a step_finish event."""

    total: int
    input: int
    output: int
    reasoning: int
    cache: dict[str, int] | None = None


class OpenCodeToolState(SerializableModel):
    """State of a tool invocation within a tool_use event."""

    status: str
    input: dict[str, Any] = Field(default_factory=dict)
    output: str | None = None
    title: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    time: dict[str, int] | None = None


class OpenCodeStepStartPart(SerializableModel):
    """Part payload for step_start events."""

    id: str
    sessionID: str
    messageID: str
    type: Literal["step-start"] = "step-start"
    snapshot: str | None = None


class OpenCodeTextPart(SerializableModel):
    """Part payload for text events."""

    id: str
    sessionID: str
    messageID: str
    type: Literal["text"] = "text"
    text: str
    time: dict[str, int] | None = None


class OpenCodeToolUsePart(SerializableModel):
    """Part payload for tool_use events."""

    id: str
    sessionID: str
    messageID: str
    type: Literal["tool"] = "tool"
    callID: str
    tool: str
    state: OpenCodeToolState


class OpenCodeStepFinishPart(SerializableModel):
    """Part payload for step_finish events."""

    id: str
    sessionID: str
    messageID: str
    type: Literal["step-finish"] = "step-finish"
    reason: str
    snapshot: str | None = None
    cost: float | None = None
    tokens: OpenCodeTokens | None = None


# OpenCode supports roughly the same tool set as Claude Code
OPENCODE_TOOLS = (
    AgentToolName.READ,
    AgentToolName.WRITE,
    AgentToolName.EDIT,
    AgentToolName.MULTI_EDIT,
    AgentToolName.GLOB,
    AgentToolName.GREP,
    AgentToolName.LS,
    AgentToolName.BASH,
    AgentToolName.BASH_OUTPUT,
    AgentToolName.KILL_SHELL,
    AgentToolName.WEB_SEARCH,
    AgentToolName.WEB_FETCH,
    AgentToolName.TASK,
    AgentToolName.TODO_READ,
    AgentToolName.TODO_WRITE,
)
