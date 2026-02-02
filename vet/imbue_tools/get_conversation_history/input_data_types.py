from typing import Self
from typing import TypeVar

from pydantic import model_validator

from vet.imbue_core.pydantic_serialization import SerializableModel
from vet.vet_types.messages import ConversationMessageUnion


class IdentifierInputsMissingError(Exception):
    pass


class IdentifierInputs(SerializableModel):
    # goal (for now, commit message) and diff to check
    maybe_goal: str | None = None
    maybe_diff: str | None = None

    # whole files to check
    maybe_files: tuple[str, ...] | None = None

    # conversation history to check
    maybe_conversation_history: tuple[ConversationMessageUnion, ...] | None = None

    diff_truncated: bool = False
    goal_truncated: bool = False
    conversation_truncated: bool = False
    extra_context_truncated: bool = False


class CommitInputs(IdentifierInputs):
    # pyre-ignore[56]: pyre's stubs don't match pydantic v2 decorator signatures
    @model_validator(mode="after")
    def validate_goal_not_none(self) -> Self:
        if self.maybe_goal is None:
            raise IdentifierInputsMissingError("goal cannot be None for CommitInputs")
        return self

    # pyre-ignore[56]: pyre's stubs don't match pydantic v2 decorator signatures
    @model_validator(mode="after")
    def validate_diff_not_none(self) -> Self:
        if self.maybe_diff is None:
            raise IdentifierInputsMissingError("goal cannot be None for CommitInputs")
        return self

    @property
    def goal(self) -> str:
        assert self.maybe_goal is not None
        return self.maybe_goal

    @property
    def diff(self) -> str:
        assert self.maybe_diff is not None
        return self.maybe_diff


class ConversationInputs(IdentifierInputs):
    # pyre-ignore[56]: pyre's stubs don't match pydantic v2 decorator signatures
    @model_validator(mode="after")
    def validate_conversation_history_not_none(self) -> Self:
        if self.maybe_conversation_history is None:
            raise IdentifierInputsMissingError("conversation_history is required for conversation inputs")
        return self

    @property
    def conversation_history(self) -> tuple[ConversationMessageUnion, ...]:
        assert self.maybe_conversation_history is not None
        return self.maybe_conversation_history


SpecificIdentifierInputsType = TypeVar("SpecificIdentifierInputsType", bound=IdentifierInputs)


def to_specific_inputs_type(
    identifier_inputs: IdentifierInputs, to_type: type[SpecificIdentifierInputsType]
) -> SpecificIdentifierInputsType:
    return to_type(**identifier_inputs.model_dump())
