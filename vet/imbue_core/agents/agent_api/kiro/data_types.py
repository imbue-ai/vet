from pathlib import Path
from typing import Literal

from vet.imbue_core.agents.agent_api.data_types import AgentOptions


class KiroOptions(AgentOptions):
    """Query options for the Kiro CLI (ACP) harness."""

    object_type: Literal["KiroOptions"] = "KiroOptions"

    model: str | None = None
    # Kiro agent config to pin. session/new otherwise inherits whatever agent
    # mode the user has locally configured as current (e.g. a custom compressed-
    # output mode), which can corrupt the judge's JSON response contract.
    agent: str | None = "kiro_default"
    cli_path: Path | None = None
    is_cached: bool = False
