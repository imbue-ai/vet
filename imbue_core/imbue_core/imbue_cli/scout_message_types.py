"""Message types for scout output."""

import time
from typing import Annotated
from typing import Literal

from pydantic import Field
from pydantic import Tag
from pydantic import TypeAdapter

from imbue_core.imbue_cli.scout_data_types import ScoutEvidenceExample
from imbue_core.pydantic_serialization import SerializableModel
from imbue_core.pydantic_serialization import build_discriminator


class ScoutMessage(SerializableModel):
    """Base class for all scout output messages."""

    object_type: str = Field(description="Discriminator field for message type")
    timestamp: float = Field(default_factory=time.time, description="Unix timestamp when message was created")


class EvidenceMessage(ScoutMessage):
    """Message containing a piece of evidence."""

    object_type: Literal["EvidenceMessage"] = "EvidenceMessage"

    # Evidence fields (same as current ScoutEvidence)
    question: str
    action: str
    result: str
    score: Literal["Good", "Moderate", "Bad"]
    confidence: Literal["High", "Medium", "Low"]
    reference: str | None = None
    examples: list[ScoutEvidenceExample] | None = None


class ScoreMessage(ScoutMessage):
    """Message containing an overall score assessment."""

    object_type: Literal["ScoreMessage"] = "ScoreMessage"

    overall_score: float  # 0.0 to 1.0
    evidence_count: int  # Number of evidence pieces contributing to this score
    score_breakdown: dict[str, int]  # Distribution of Good/Moderate/Bad evidence counts
    confidence_breakdown: dict[str, int]  # Distribution of High/Medium/Low confidence counts
    time_elapsed: float  # Time elapsed since start in seconds


class MetadataMessage(ScoutMessage):
    """Message containing metadata about the scout run."""

    object_type: Literal["MetadataMessage"] = "MetadataMessage"

    goal: str
    repo_path: str
    model: str
    started_at: float


class CostMessage(ScoutMessage):
    """Message containing cost information."""

    object_type: Literal["CostMessage"] = "CostMessage"

    total_cost_usd: float
    tokens_used: int | None = None


class StatusMessage(ScoutMessage):
    """Message containing status updates."""

    object_type: Literal["StatusMessage"] = "StatusMessage"

    status: Literal["started", "running", "completed", "failed"]
    message: str | None = None


# Union type for all messages
ScoutMessageUnion = Annotated[
    (
        Annotated[EvidenceMessage, Tag("EvidenceMessage")]
        | Annotated[ScoreMessage, Tag("ScoreMessage")]
        | Annotated[MetadataMessage, Tag("MetadataMessage")]
        | Annotated[CostMessage, Tag("CostMessage")]
        | Annotated[StatusMessage, Tag("StatusMessage")]
    ),
    build_discriminator(),
]

_scout_message_type_adapter = TypeAdapter(ScoutMessageUnion)


def deserialize_scout_message_json(data: str) -> ScoutMessageUnion:
    print(f"Parsing scout message json: {data}")
    return _scout_message_type_adapter.validate_json(data)
