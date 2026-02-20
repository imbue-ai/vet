from typing import Literal

from vet.imbue_core.agents.agent_api.data_types import AgentOptions
from vet.imbue_core.agents.agent_api.data_types import AgentToolName

SmolagentsAgentType = Literal["tool_calling", "code"]


class SmolagentsOptions(AgentOptions):
    object_type: Literal["SmolagentsOptions"] = "SmolagentsOptions"

    model: str = "anthropic/claude-sonnet-4-5-20250929"
    agent_type: SmolagentsAgentType = "tool_calling"
    max_steps: int = 30
    verbosity_level: int = 0
    is_cached: bool = False


SMOLAGENTS_TOOLS = (
    AgentToolName.READ,
    AgentToolName.GREP,
    AgentToolName.GLOB,
    AgentToolName.LS,
)
