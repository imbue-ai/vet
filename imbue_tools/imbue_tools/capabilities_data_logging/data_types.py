"""
Any fields in this file that are optional are not strictly required to be present in the database.
Any fields that are non-optional are required and should not be changed without talking to capabilities eval group.
Much of this code is taken from an unmerged branch `pranali/backwards_compatibility`.
The write_code event is also supported in the minimal format in that branch.
"""

import uuid
from datetime import datetime
from datetime import timezone
from enum import StrEnum
from typing import Annotated
from typing import Any
from typing import Callable
from typing import Self
from typing import TypeVar

from pydantic import ConfigDict
from pydantic import Field
from pydantic import PlainValidator
from pydantic import ValidationError
from pydantic import field_validator
from pydantic import model_validator

from imbue_core.agents.configs import LanguageModelGenerationConfig
from imbue_core.common import generate_id
from imbue_core.data_types import IdentifiedVerifyIssue
from imbue_core.data_types import LLMResponse
from imbue_core.frozen_utils import FrozenDict
from imbue_core.frozen_utils import empty_mapping
from imbue_core.nested_evolver import assign
from imbue_core.nested_evolver import chill
from imbue_core.nested_evolver import evolver
from imbue_core.pydantic_serialization import SerializableModel
from imbue_core.repo_state import RepoState
from imbue_core.sculptor.state.messages import ConversationMessageUnion
from imbue_tools.repo_utils.context_prefix import SubrepoContext
from imbue_tools.types.imbue_verify_config import ImbueVerifyConfig

TypeInput = TypeVar("TypeInput")
TypeOutput = TypeVar("TypeOutput")


class UnknownFeatureType(Exception):
    """Exception raised when an unknown feature type is encountered."""


class LoggedFeatureType(StrEnum):
    VERIFY_EXCEPTION = "VERIFY_EXCEPTION"
    COMMAND_RUN = "COMMAND_RUN"
    ISSUE_FEEDBACK = "ISSUE_FEEDBACK"
    UNKNOWN = "UNKNOWN"


class CommandType(StrEnum):
    IMBUE_VERIFY = "IMBUE_VERIFY"


# TODO this is WEIRD
EVENT_BY_LOGGED_FEATURE_TYPE: dict[LoggedFeatureType, Callable[[], type["CapabilitiesLoggedEvent"]]] = {
    LoggedFeatureType.VERIFY_EXCEPTION: lambda: ImbueVerifyEvent,
    LoggedFeatureType.COMMAND_RUN: lambda: ImbueVerifyEvent,
    LoggedFeatureType.ISSUE_FEEDBACK: lambda: IssueFeedbackReport,
}

# TODO: had to pull in code from crafty in here to make this work, revisit what needs to stay, what should become shared, what we don't need


def make_string_safe_for_formatting(s: str) -> str:
    """
    Make a string safe for things like str.format()
    """
    # Replace each '{' with '{{' and each '}' with '}}'
    return s.replace("{", "{{").replace("}", "}}")


class IssueKey(SerializableModel):
    # TODO: this should likely be shared with the product code in v1
    issue_type: CommandType
    # this should NOT contain line numbers, as we want it to be stable across changes as much as possible
    # NOTE: we do some initial formatting to avoid issues around message containing code
    message: Annotated[str, PlainValidator(make_string_safe_for_formatting)]

    # NOTE: this is the error code for pyre, ruff, and imbue_verify, and the test name for pytest
    error_type: str | None = None

    def commit_message(self) -> str:
        return f"Fix {self.issue_type} issue: {self.message[:20]}"


class CapabilitiesLoggedEvent(SerializableModel):
    # TODO: Maybe convert empty optional strings and tuples and other datatypes to be Nones so there is only one notion of emptiness
    # Though in some cases there actually is a difference: eg current_issues not existing or there being 0
    # Null values are generally going to correspond to (possibly intentionally) 'missing' data
    """
    Most types in this class are optional since they may not be present for every type of event.
    In the future additional fields may be added to this class to support new events, but they should be optional.
    """

    model_config = ConfigDict(frozen=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    user_id: str
    organization_id: str
    git_url: str | None = None
    git_hash: str | None = None
    subrepo_context: SubrepoContext | None = None
    instruction_context: SubrepoContext | None = None
    conversation_history: tuple[ConversationMessageUnion, ...] | None = None

    server_version: FrozenDict[str, Any] = Field(default_factory=empty_mapping)

    feature_name: LoggedFeatureType | None = None
    repo_state: RepoState | None = None

    # TODO: Add configuration settings about how sculptor was started

    # Command run specific fields
    diff: str | None = None
    command_type: CommandType | None = None
    task_description: str | None = None
    # For feedback
    issue_key: IssueKey | None = None

    # Output fields
    has_output: bool = False
    output_completion_time: datetime | None = None
    llm_response: str | None = Field(default=None, deprecated=True)
    llm_responses: tuple[LLMResponse, ...] | None = None
    # Command run output fields
    issues: tuple[IdentifiedVerifyIssue, ...] | None = None

    # Feedback fields
    feedback_rating: str | None = None
    feedback_text: str | None = None

    # Imbue verify specific fields
    generation_config: LanguageModelGenerationConfig | None = None
    imbue_verify_config: ImbueVerifyConfig | None = None

    # pyre-ignore[56]: pyre's stubs don't match pydantic v2 decorator signatures
    @field_validator("server_version", mode="before")
    @classmethod
    def validate_server_version(cls, v: Any) -> Any:
        if isinstance(v, dict):
            return FrozenDict(v)
        return v

    @classmethod
    def build_from_json(cls, json_data: str) -> "CapabilitiesLoggedEvent":
        # mypy is unhappy if this is -> Self because of event = event_type.build_from_json(json_data) below
        event = cls.model_validate_json(json_data)
        if event.feature_name:
            feature_name = event.feature_name
            if feature_name in EVENT_BY_LOGGED_FEATURE_TYPE:
                event_type = EVENT_BY_LOGGED_FEATURE_TYPE[feature_name]()
                try:
                    event = event_type.build_from_json(json_data)
                except ValidationError as e:
                    print(e)
        return event

    def build_new_event_with_outputs(self, outputs: Any) -> Self:
        raise NotImplementedError("Should be implemented by subclasses")


class ImbueVerifyUsage(SerializableModel):
    model_config = ConfigDict(frozen=True)

    num_llm_calls: int
    total_cost: float
    total_input_tokens: int
    total_output_tokens: int
    total_cache_creation_tokens: int
    total_cache_read_tokens: int


class CostedImbueVerifyEvent(SerializableModel):
    model_config = ConfigDict(frozen=True)
    event: "ImbueVerifyEvent"
    usage: ImbueVerifyUsage


class ImbueVerifyEvent(CapabilitiesLoggedEvent):
    """
    Events for `imbue_verify`.
    """

    diff: str
    command_type: CommandType
    feature_name: LoggedFeatureType = LoggedFeatureType.COMMAND_RUN

    task_description: str
    generation_config: LanguageModelGenerationConfig
    imbue_verify_config: ImbueVerifyConfig = Field(default_factory=ImbueVerifyConfig)
    server_version: FrozenDict[str, Any] = Field(default_factory=empty_mapping)
    # TODO: Get the direct llm response for command run events as well

    exception_name: str | None = None

    # pyre-ignore[56]: pyre's stubs don't match pydantic v2 decorator signatures
    @model_validator(mode="after")
    def ensure_reasonable_output(self) -> Self:
        if self.has_output:
            if self.issues is None:
                raise ValueError("If has_output is True, there must be some issues")
        return self

    # TODO the only sites at which this is constructed have this info available.
    # should simplify by providing it at construction time rather than using evolver
    def build_new_event_with_outputs(
        self,
        outputs: tuple[tuple[IdentifiedVerifyIssue, ...], tuple[LLMResponse, ...], str | None],
    ) -> Self:
        issues, llm_responses, git_url = outputs
        event_evolver = evolver(self)
        assign(event_evolver.issues, lambda: issues)
        assign(event_evolver.llm_responses, lambda: llm_responses)
        assign(event_evolver.has_output, lambda: True)
        assign(event_evolver.id, lambda: generate_id())
        assign(event_evolver.output_completion_time, lambda: datetime.now(timezone.utc))
        assign(event_evolver.git_url, lambda: git_url)
        event_with_outputs = chill(event_evolver)
        return event_with_outputs

    @classmethod
    def build_from_json(cls, json_data: str) -> Self:
        return cls.model_validate_json(json_data)


class IssueFeedbackReport(CapabilitiesLoggedEvent):
    # TODO: this is copied and not updated from crafty
    issue_key: IssueKey
    device_id: str | None = None
    session_id: str | None = None
    browser_id: str | None = None
    tab_id: str | None = None
    feature_name: LoggedFeatureType = LoggedFeatureType.ISSUE_FEEDBACK

    # pyre-ignore[56]: pyre's stubs don't match pydantic v2 decorator signatures
    @model_validator(mode="after")
    def has_some_feedback(self) -> Self:
        if self.feedback_rating is None and self.feedback_text is None:
            raise ValueError("At least one of feedback_rating or feedback_text must be set")
        return self

    @classmethod
    def build_from_json(cls, json_data: str) -> "IssueFeedbackReport":
        event = IssueFeedbackReport.model_validate_json(json_data)
        return event
