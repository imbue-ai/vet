import datetime
import enum
import math
from abc import ABC
from typing import Any
from typing import Generic
from typing import TypeVar

import attr
from pydantic import ValidationInfo
from pydantic import field_validator

from imbue_core.agents.llm_apis.union_data_types import ProviderSpecificCachingInfoUnion
from imbue_core.pydantic_serialization import SerializableModel
from imbue_core.serialization_types import Serializable
from imbue_core.time_utils import get_current_time

__all__ = [
    "CachedCostedLanguageModelResponse",
    "ConversationMessage",
    "CostedLanguageModelResponse",
    "LanguageModelCompleteInputs",
    "LanguageModelResponse",
    "LanguageModelResponseUsage",
    "LanguageModelResponseWithLogits",
    "LanguageModelResponseWithThoughts",
    "LanguageModelStreamInputs",
    "ModelStr",
    "ResponseStopReason",
    "TokenProbability",
]


class ConversationMessage(SerializableModel):
    role: str
    content: str


class ResponseStopReason(enum.StrEnum):
    END_TURN = "end_turn"
    MAX_TOKENS = "max_tokens"
    STOP_SEQUENCE = "stop_sequence"
    ERROR = "error"
    NONE = "none"
    # TODO: We aren't handling any of the below, we should likely error in these cases
    CONTENT_FILTER = "content_filter"
    TOOL_CALLS = "tool_calls"
    FUNCTION_CALL = "function_call"

    def response_not_finished(self) -> bool:
        return self in {self.CONTENT_FILTER, self.MAX_TOKENS, self.ERROR}


class TokenProbability(SerializableModel):
    token: str
    log_probability: float
    is_stop: bool

    @property
    def probability(self) -> float:
        return math.exp(self.log_probability)


class ModelResponse(ABC):
    pass


class ThoughtResponse(SerializableModel, ModelResponse):
    text: str
    completion_tokens: int


@attr.s(auto_attribs=True, frozen=True)
class LanguageModelResponse(Serializable, ModelResponse):
    text: str
    token_count: int
    stop_reason: ResponseStopReason
    network_failure_count: int

    def get_token_probability_sequence(self) -> tuple[tuple[TokenProbability, ...], ...] | None:
        return None


@attr.s(auto_attribs=True, frozen=True)
class LanguageModelResponseWithThoughts(LanguageModelResponse):
    thoughts: ThoughtResponse | None = None


@attr.s(auto_attribs=True, frozen=True)
class LanguageModelResponseWithLogits(LanguageModelResponse):
    # guarantees that the first in each sequence was the one that was selected.
    # the inner sequence are *not* guaranteed to be the same length, nor are they guaranteed to be sorted
    token_probabilities: tuple[tuple[TokenProbability, ...], ...]

    def get_token_probability_sequence(self) -> tuple[tuple[TokenProbability, ...], ...] | None:
        return self.token_probabilities


@attr.s(auto_attribs=True, frozen=True)
class CountTokensResponse(Serializable, ModelResponse):
    input_tokens: int
    cached_content_token_count: int | None = None


class CachingInfo(SerializableModel):
    read_from_cache: int

    # this should contain info that's not the same between providers. e.g. anthropic requires explicit cache writes with 5m or 1h duration,
    # whereas openai does automatic prompt caching at no extra cost; so, we store cache write info here
    provider_specific_data: ProviderSpecificCachingInfoUnion | None = None


class LanguageModelResponseUsage(SerializableModel):
    prompt_tokens_used: int
    completion_tokens_used: int
    dollars_used: float
    caching_info: CachingInfo | None = None


@attr.s(auto_attribs=True, frozen=True)
class CostedLanguageModelResponse(Serializable, ModelResponse):
    usage: LanguageModelResponseUsage
    responses: tuple[LanguageModelResponse, ...]


class ThinkConfig(SerializableModel):
    # watch out: at least for gemini, this is a soft limit!
    max_tokens: int | None = None
    output_thinking: bool = False


class LanguageModelGenerationParams(SerializableModel):
    """Parameters for a single API call to an LLM. Excludes things that you don't want a default for, e.g. the prompt."""

    temperature: float = 0.2
    count: int = 1
    max_tokens: int | None = None
    stop: str | None = None
    # specifically to allow generating new responses even when using caching
    seed: int | None = None
    thinking: ThinkConfig | None = None


class ModelInputs(SerializableModel, ABC):
    """Base class for inputs to an LLM API call."""


class LanguageModelCompleteInputs(ModelInputs):
    """Used to serialize the inputs for an LLM complete call."""

    prompt: str
    params: LanguageModelGenerationParams
    network_failure_count: int


class LanguageModelStreamInputs(ModelInputs):
    """Used to serialize the inputs for an LLM stream call."""

    prompt: str
    params: LanguageModelGenerationParams


class CountTokensInputs(ModelInputs):
    """Used to serialize the inputs for a token count call."""

    model: str
    prompt: str


InputsT = TypeVar("InputsT", bound=ModelInputs)
ModelResponseT = TypeVar("ModelResponseT", bound=ModelResponse)


@attr.s(auto_attribs=True, frozen=True)
class CachedCostedModelResponse(Serializable, Generic[InputsT, ModelResponseT]):
    response: ModelResponseT | None = None
    error: str | None = None

    # The timestamp is used to order cache entries when checking them in unit tests.
    timestamp: datetime.datetime = attr.ib(factory=get_current_time)

    # Cache entries are keyed based on an MD5 hash of the inputs to prevent the cache from growing too large.
    # Here, we optionally store the inputs to the request.
    # This is useful for unit tests to highlight changes in the prompt and other parts of the request.
    # But since it can grow very large, we don't always store this information.
    inputs: InputsT | None = None

    @field_validator("response", "error")
    def validate_response_or_error(cls, v: Any, info: ValidationInfo) -> Any:
        if "response" in info.data and "error" in info.data:
            if not ((info.data["response"] is None) ^ (info.data["error"] is None)):
                raise ValueError("Must provide exactly one of response or error")
        return v


class CachedCostedLanguageModelResponse(
    CachedCostedModelResponse[LanguageModelCompleteInputs | LanguageModelStreamInputs, CostedLanguageModelResponse]
):
    pass


class CachedCountTokensResponse(CachedCostedModelResponse[CountTokensInputs, CountTokensResponse]):
    pass


# to allow type checking to work when model names are passed as strings
ModelStr = str
