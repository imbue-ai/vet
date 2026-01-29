from typing import Annotated
from typing import Any

from pydantic import AnyUrl
from pydantic import Field
from pydantic import Tag

from imbue_core.agents.data_types.ids import ObjectID
from imbue_core.data_types import IdentifiedVerifyIssue
from imbue_core.pydantic_serialization import SerializableModel
from imbue_core.pydantic_serialization import build_discriminator


class SuggestionAction(SerializableModel):
    object_type: str
    # more important -> lower number. Think about it as "my first priority is to..."
    # different actions *may* share the same priority rank, in which case the ties will be broken by a canonical ordering of importance
    priority_rank: int = 0


class UseSuggestionAction(SuggestionAction):
    object_type: str = "UseSuggestionAction"
    content: str


class VisitLinkSuggestionAction(SuggestionAction):
    object_type: str = "VisitLinkSuggestionAction"
    url: AnyUrl
    link_text: str


SuggestionActionTypes = Annotated[
    Annotated[UseSuggestionAction, Tag("UseSuggestionAction")]
    | Annotated[VisitLinkSuggestionAction, Tag("VisitLinkSuggestionAction")],
    build_discriminator(),
]


# FIXME(johnny): move to imbue_core.imbue_cli.action
class CheckOutputID(ObjectID):
    tag: str = "chko"


class Suggestion(SerializableModel):
    # TODO: this is here because we're treating this like an issue, but we may not want to do that
    object_type: str = "Suggestion"
    # TODO: remove the default factory once we have properly migrated to the new check output protocol
    # Also see sculptor/sculptor/tasks/handlers/run_agent/checks/check_process.py::275
    id: CheckOutputID = Field(default_factory=CheckOutputID)
    title: str = Field(min_length=1)
    description: str = ""
    # (if sculptor speaks true) pyre doesn't like float values for gt/ge/le because... it's looking for def __gt__(self: T, __other: T) -> bool and float has def __gt__(self, value: float, /) -> bool

    # will probably be technically implemented by asking an LLM to come up with a number between 1 and 10,
    # so probably really will range between 0.1 and 1.0
    severity_score: float = Field(
        ge=0.0,  # pyre-ignore[6]
        le=1.0,  # pyre-ignore[6]
        description="A score between 0.0 and 1.0 indicating how severe the issue is that this suggestion addresses.",
    )
    # unlike the severity, this is about how sure we are that this is a good suggestion,
    # for example, you can be confident that there is a real problem (high confidence_score)
    # but it might be about some edge case that doesn't matter (low severity_score)
    confidence_score: float = Field(
        ge=0.0,  # pyre-ignore[6]
        le=1.0,  # pyre-ignore[6]s
        description="A score between 0.0 and 1.0 indicating how confident we are that this suggestion addresses a real issue.",
    )
    # these are the possible actions that the user can take with this suggestion
    # for right now, the only ones implemented are "USE" and "COPY"
    actions: tuple[SuggestionActionTypes, ...]
    original_issues: tuple[IdentifiedVerifyIssue, ...]


# FIXME(johnny): move these to the right location, use the right types, etc -- these are just placeholders to demonstrate how this works
# FIXME(johnny): migrate to just using the ActionOutputUnion from imbue_core.imbue_cli.action
CheckOutputTypes = Annotated[
    Annotated[Suggestion, Tag("Suggestion")],
    build_discriminator(),
]


# FIXME(johnny): remove this once we move to using the ActionOutputUnion from imbue_core.imbue_cli.action
def is_check_output(output: Any) -> bool:
    return isinstance(output, Suggestion)
