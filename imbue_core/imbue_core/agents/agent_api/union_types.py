from typing import Annotated

from pydantic import Tag

from imbue_core.agents.agent_api.claude.data_types import ClaudeCodeOptions
from imbue_core.agents.agent_api.codex.data_types import CodexOptions
from imbue_core.pydantic_serialization import build_discriminator

AgentOptionsUnion = Annotated[
    Annotated[ClaudeCodeOptions, Tag("ClaudeCodeOptions")] | Annotated[CodexOptions, Tag("CodexOptions")],
    build_discriminator(),
]
