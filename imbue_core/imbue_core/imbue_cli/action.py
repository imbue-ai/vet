from typing import Annotated
from typing import Literal

from pydantic import Field
from pydantic import Tag

from imbue_core.imbue_cli.scout_message_types import ScoutMessageUnion
from imbue_core.issues import CheckFailedIssue
from imbue_core.issues import IdentifiedIssue
from imbue_core.pydantic_serialization import SerializableModel
from imbue_core.pydantic_serialization import build_discriminator
from imbue_core.suggestions import CheckOutputID
from imbue_core.suggestions import Suggestion


class UserDisplayOutput(SerializableModel):
    object_type: str


class ErroredOutput(UserDisplayOutput):
    object_type: Literal["ErroredOutput"] = "ErroredOutput"
    error_message: str


class CommandTextOutput(UserDisplayOutput):
    object_type: Literal["CommandTextOutput"] = "CommandTextOutput"
    output: str


class CommandHTMLOutput(UserDisplayOutput):
    object_type: Literal["CommandHTMLOutput"] = "CommandHTMLOutput"
    output: str


UserDisplayOutputUnion = Annotated[
    Annotated[ErroredOutput, Tag("ErroredOutput")]
    | Annotated[CommandTextOutput, Tag("CommandTextOutput")]
    | Annotated[CommandHTMLOutput, Tag("CommandHTMLOutput")],
    build_discriminator(),
]


class RetrieveOutput(SerializableModel):
    object_type: str = "RetrieveOutput"
    files: tuple[str, ...]


class ScoutOutput(SerializableModel):
    object_type: str = "ScoutOutput"
    id: CheckOutputID
    data: ScoutMessageUnion


ActionOutputUnion = Annotated[
    (
        Annotated[ScoutOutput, Tag("ScoutOutput")]
        | Annotated[Suggestion, Tag("Suggestion")]
        | Annotated[CheckFailedIssue, Tag("CheckFailedIssue")]
        | Annotated[IdentifiedIssue, Tag("IdentifiedIssue")]
        | Annotated[RetrieveOutput, Tag("RetrieveOutput")]
    ),
    build_discriminator(),
]


class ActionOutput(SerializableModel):
    command: str = Field(
        description="The command that was executed to produce the output."
    )
    outputs: tuple[ActionOutputUnion, ...] = Field(
        description="The structured output data from the action."
    )
    user_display: UserDisplayOutputUnion = Field(
        description="The user display output from the action. This can be used by consumers to display a user-friendly version of the action output."
    )
