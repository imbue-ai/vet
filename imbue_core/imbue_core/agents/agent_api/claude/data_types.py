from pathlib import Path
from typing import Literal

from pydantic import Field

from imbue_core.agents.agent_api.data_types import AgentOptions
from imbue_core.agents.agent_api.data_types import AgentToolName
from imbue_core.pydantic_serialization import SerializableModel

ClaudePermissionMode = Literal["plan", "default", "acceptEdits", "bypassPermissions"]


class ClaudeMcpStdioServerConfig(SerializableModel):
    """MCP stdio server configuration."""

    type: Literal["stdio"] = "stdio"
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)


class ClaudeMcpHttpServerConfig(SerializableModel):
    """MCP HTTP server configuration."""

    type: Literal["http"] = "http"
    url: str
    headers: dict[str, str] | None = None


ClaudeMcpServerConfig = ClaudeMcpStdioServerConfig | ClaudeMcpHttpServerConfig


class ClaudeCodeOptions(AgentOptions):
    """Query options for Claude SDK."""

    object_type: Literal["ClaudeCodeOptions"] = "ClaudeCodeOptions"

    allowed_tools: list[str] = Field(default_factory=list)
    max_thinking_tokens: int = 8000
    system_prompt: str | None = None
    append_system_prompt: str | None = None
    mcp_tools: list[str] = Field(default_factory=list)
    mcp_servers: dict[str, ClaudeMcpServerConfig] = Field(default_factory=dict)
    permission_mode: ClaudePermissionMode | None = None
    continue_conversation: bool = False
    resume: str | None = None
    max_turns: int | None = None
    disallowed_tools: list[str] = Field(default_factory=list)
    model: str | None = None
    permission_prompt_tool_name: str | None = None
    # Optional override for the Claude CLI path
    cli_path: Path | None = None
    is_cached: bool = False


CLAUDE_TOOLS = (
    AgentToolName.READ,
    AgentToolName.WRITE,
    AgentToolName.EDIT,
    AgentToolName.MULTI_EDIT,
    AgentToolName.GLOB,
    AgentToolName.NOTEBOOK_READ,
    AgentToolName.NOTEBOOK_EDIT,
    AgentToolName.LS,
    AgentToolName.GREP,
    AgentToolName.BASH,
    AgentToolName.BASH_OUTPUT,
    AgentToolName.KILL_SHELL,
    AgentToolName.WEB_SEARCH,
    AgentToolName.WEB_FETCH,
    AgentToolName.TASK,
    AgentToolName.TODO_READ,
    AgentToolName.TODO_WRITE,
    AgentToolName.SLASH_COMMAND,
    AgentToolName.EXIT_PLAN_MODE,
    AgentToolName.MCP_TOOL,
    AgentToolName.LIST_MCP_RESOURCES,
    AgentToolName.READ_MCP_RESOURCE,
)
