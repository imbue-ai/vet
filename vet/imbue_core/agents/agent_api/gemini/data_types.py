"""Data types for Gemini CLI agent integration."""

from pathlib import Path
from typing import Annotated
from typing import Any
from typing import Literal

from pydantic import Field
from pydantic import Tag

from vet.imbue_core.agents.agent_api.data_types import AgentOptions
from vet.imbue_core.pydantic_serialization import SerializableModel
from vet.imbue_core.pydantic_serialization import build_discriminator


class GeminiOptions(AgentOptions):
    """Options for Gemini CLI execution."""

    object_type: Literal["GeminiOptions"] = "GeminiOptions"

    model: str | None = None
    cli_path: Path | None = None


# Gemini stream JSON event models
class GeminiInitEvent(SerializableModel):
    type: Literal["init"]
    timestamp: str
    session_id: str
    model: str


class GeminiMessageEvent(SerializableModel):
    type: Literal["message"]
    timestamp: str
    role: Literal["user", "assistant", "system"]
    content: str
    delta: bool | None = None


class GeminiStats(SerializableModel):
    total_tokens: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached: int | None = None
    duration_ms: int | None = None
    tool_calls: int | None = None


class GeminiResultEvent(SerializableModel):
    type: Literal["result"]
    timestamp: str
    status: Literal["success", "error"]
    stats: GeminiStats | None = None
    error: str | None = None


class GeminiToolUseEvent(SerializableModel):
    type: Literal["tool_use"]
    timestamp: str
    tool_name: str
    tool_id: str
    parameters: dict[str, Any]


class GeminiToolResultEvent(SerializableModel):
    type: Literal["tool_result"]
    timestamp: str
    tool_name: str | None = None
    tool_id: str
    output: Any
    status: Literal["success", "error"] | None = None
    is_error: bool | None = None


GeminiStreamEventUnion = Annotated[
    Annotated[GeminiInitEvent, Tag("init")]
    | Annotated[GeminiMessageEvent, Tag("message")]
    | Annotated[GeminiResultEvent, Tag("result")]
    | Annotated[GeminiToolUseEvent, Tag("tool_use")]
    | Annotated[GeminiToolResultEvent, Tag("tool_result")],
    build_discriminator("type"),
]
