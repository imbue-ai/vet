from typing import Literal

from imbue_core.pydantic_serialization import SerializableModel

# TODO refactor evidence example to use different classes for different output types


class ScoutEvidenceExample(SerializableModel):
    """A single example of evidence for the report."""

    description: str
    type: Literal["positive", "negative"]
    command: str | None = None
    output: str | None = None
    code: str | None = None
    image_path: str | None = None
    image_data: bytes | None = None
    image_format: str | None = None
    image_caption: str | None = None


class ScoutEvidence(SerializableModel):
    """A piece of evidence for the report."""

    question: str
    action: str
    result: str
    score: Literal["Good", "Moderate", "Bad"]
    confidence: Literal["High", "Medium", "Low"]
    reference: str | None = None
    examples: list[ScoutEvidenceExample] | None = None


class ScoutReport(SerializableModel):
    """A report of the scout analysis."""

    goal: str
    evidence: list[ScoutEvidence]
    total_cost: float
    total_time_taken: float
