import enum
import inspect
from contextlib import contextmanager
from pathlib import Path
from types import FrameType
from typing import AsyncGenerator
from typing import Callable
from typing import Final
from typing import Iterable
from typing import Iterator
from typing import TypeVar

import google.genai as genai
import httpx
from google.genai.errors import APIError
from google.genai.types import BlockedReason
from google.genai.types import ContentListUnion
from google.genai.types import ContentUnion
from google.genai.types import FinishReason
from google.genai.types import GenerateContentConfig
from google.genai.types import GenerateContentResponse
from google.genai.types import HarmProbability
from google.genai.types import ModelContent
from google.genai.types import Part
from google.genai.types import ThinkingConfig
from google.genai.types import UserContent
from loguru import logger
from pydantic.functional_validators import field_validator

from vet.imbue_core.agents.llm_apis.api_utils import convert_prompt_to_messages
from vet.imbue_core.agents.llm_apis.api_utils import create_costed_language_model_response_for_single_result
from vet.imbue_core.agents.llm_apis.data_types import CachedCountTokensResponse
from vet.imbue_core.agents.llm_apis.data_types import CostedLanguageModelResponse
from vet.imbue_core.agents.llm_apis.data_types import CountTokensInputs
from vet.imbue_core.agents.llm_apis.data_types import CountTokensResponse
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelGenerationParams
from vet.imbue_core.agents.llm_apis.data_types import ResponseStopReason
from vet.imbue_core.agents.llm_apis.data_types import ThoughtResponse
from vet.imbue_core.agents.llm_apis.errors import BadAPIRequestError
from vet.imbue_core.agents.llm_apis.errors import LanguageModelInvalidModelNameError
from vet.imbue_core.agents.llm_apis.errors import MissingAPIKeyError
from vet.imbue_core.agents.llm_apis.errors import TransientLanguageModelError
from vet.imbue_core.agents.llm_apis.errors import UnsetCachePathError
from vet.imbue_core.agents.llm_apis.language_model_api import LanguageModelAPI
from vet.imbue_core.agents.llm_apis.models import ModelInfo
from vet.imbue_core.agents.llm_apis.stream import LanguageModelStreamEvent
from vet.imbue_core.async_monkey_patches import log_exception
from vet.imbue_core.caching import AsyncCache
from vet.imbue_core.frozen_utils import FrozenDict
from vet.imbue_core.frozen_utils import FrozenMapping
from vet.imbue_core.itertools import only
from vet.imbue_core.secrets_utils import get_secret


class GeminiModelName(enum.StrEnum):
    # GA models
    GEMINI_2_5_FLASH = "gemini-2.5-flash"
    GEMINI_2_5_FLASH_LITE = "gemini-2.5-flash-lite"
    # Preview models
    GEMINI_3_FLASH_PREVIEW = "gemini-3-flash-preview"
    GEMINI_3_1_PRO_PREVIEW = "gemini-3.1-pro-preview"


# Rate limits for Google Gemini models based on published API documentation
# Reference: https://ai.google.dev/gemini-api/docs/rate-limits#tier-3
# Using Tier 3 rate limits
#
# Pricing references:
# - https://cloud.google.com/vertex-ai/generative-ai/pricing
# - https://ai.google.dev/pricing
# For pricing there are different rates depending on context/prompt size, so below we use the most
# expensive value (the >200K token tier for 2.5+ models).

GEMINI_MODEL_INFO_BY_NAME: FrozenMapping[GeminiModelName, ModelInfo] = FrozenDict(
    {
        GeminiModelName.GEMINI_2_5_FLASH: ModelInfo(
            model_name="gemini-2.5-flash",
            cost_per_input_token=0.30 / 1_000_000,
            cost_per_output_token=2.50 / 1_000_000,
            max_input_tokens=1_048_576,
            max_output_tokens=65_536,
            rate_limit_req=10_000 / 60,  # 10000 RPM = 166.67 RPS
            rate_limit_tok=8_000_000 / 60,  # 8,000,000 TPM = 133,333.33 TPS
            max_thinking_budget=24_576,
        ),
        GeminiModelName.GEMINI_2_5_FLASH_LITE: ModelInfo(
            model_name="gemini-2.5-flash-lite",
            cost_per_input_token=0.10 / 1_000_000,
            cost_per_output_token=0.40 / 1_000_000,
            max_input_tokens=1_048_576,
            max_output_tokens=65_535,
            rate_limit_req=10_000 / 60,
            rate_limit_tok=10_000_000 / 60,
            max_thinking_budget=24_576,
        ),
        GeminiModelName.GEMINI_3_FLASH_PREVIEW: ModelInfo(
            model_name="gemini-3-flash-preview",
            cost_per_input_token=0.50 / 1_000_000,
            cost_per_output_token=3.0 / 1_000_000,
            max_input_tokens=1_048_576,
            max_output_tokens=65_536,
            rate_limit_req=10_000 / 60,  # 10000 RPM = 166.67 RPS
            rate_limit_tok=8_000_000 / 60,  # 8,000,000 TPM = 133,333.33 TPS
            max_thinking_budget=24_576,
        ),
        GeminiModelName.GEMINI_3_1_PRO_PREVIEW: ModelInfo(
            model_name="gemini-3.1-pro-preview",
            cost_per_input_token=4.0 / 1_000_000,
            cost_per_output_token=18.0 / 1_000_000,
            max_input_tokens=1_048_576,
            max_output_tokens=65_536,
            rate_limit_req=4_000 / 60,  # 4000 RPM = 66.67 RPS
            rate_limit_tok=8_000_000 / 60,  # 8,000,000 TPM = 133,333.33 TPS
            max_thinking_budget=24_576,
        ),
    }
)


_ROLE_TO_GEMINI_ROLE: Final[FrozenMapping[str, str]] = FrozenDict(
    {
        "HUMAN": "user",
        "ASSISTANT": "model",
        "USER": "user",
        "SYSTEM": "user",
    }
)

NO_SIMPLE_TEXT_ERROR = "".join(
    [
        "The `response.text` quick accessor only works for ",
        "simple (single-`Part`) text responses. This response is not simple text.",
        "Use the `result.parts` accessor or the full ",
        "`result.candidates[index].content.parts` lookup ",
        "instead.",
    ]
)

_GEMINI_STOP_REASON_TO_STOP_REASON: Final[FrozenMapping[FinishReason, ResponseStopReason]] = FrozenDict(
    {
        # Gemini treats stop due to natural stop point and provided stop sequence the same
        FinishReason.STOP: ResponseStopReason.END_TURN,
        FinishReason.MAX_TOKENS: ResponseStopReason.MAX_TOKENS,
        FinishReason.SAFETY: ResponseStopReason.CONTENT_FILTER,
        # Recitation means the content was flagged for being memorized, i.e. the LLM just
        # copied data from the training data (@johnny at least that's how I understood the docs)
        # https://ai.google.dev/api/generate-content#FinishReason
        FinishReason.RECITATION: ResponseStopReason.CONTENT_FILTER,
        FinishReason.OTHER: ResponseStopReason.NONE,
        FinishReason.FINISH_REASON_UNSPECIFIED: ResponseStopReason.NONE,
    }
)

T = TypeVar("T")


def only_and_not_none(iterable: Iterable[T] | None) -> T:
    in_value = iterable if iterable is not None else []
    return only(in_value)


def _is_flagged_as_unsafe(api_result: GenerateContentResponse) -> bool:
    if api_result.prompt_feedback is None:
        return False
    block_reason = api_result.prompt_feedback.block_reason
    if block_reason == BlockedReason.SAFETY:
        return True
    candidate = only_and_not_none(api_result.candidates)
    if candidate.finish_reason == FinishReason.SAFETY:
        return True
    if candidate.finish_reason == FinishReason.OTHER and any(
        rating.probability != HarmProbability.NEGLIGIBLE for rating in (candidate.safety_ratings or [])
    ):
        return True
    return False


def _is_flagged_as_recitation(api_result: GenerateContentResponse) -> bool:
    candidate = only_and_not_none(api_result.candidates)
    finish_reason = candidate.finish_reason
    if finish_reason == FinishReason.RECITATION:
        return True
    return False


def role_to_content(role: str, parts: list[Part]) -> ContentUnion:
    match role:
        case "user":
            return UserContent(parts=parts)
        case "model":
            return ModelContent(parts=parts)
        case _:
            raise BadAPIRequestError(f"Invalid role: {role}")


def convert_prompt_to_gemini_messages(prompt: str) -> ContentListUnion:
    messages: list[ContentUnion] = []
    parts = []
    last_role = None
    for message in convert_prompt_to_messages(prompt):
        role = _ROLE_TO_GEMINI_ROLE[message.role]
        parts.append(Part(text=f"\n{message.content}"))
        if last_role != role and last_role is not None:
            messages.append(role_to_content(last_role, parts))
            parts = []
        last_role = role
    if len(parts) > 0:
        assert last_role is not None
        messages.append(role_to_content(last_role, parts))
    return messages


@contextmanager
def _gemini_exception_manager() -> Iterator[None]:
    """Simple context manager for parsing gemini API exceptions."""
    # TODO probably some exceptions missing here. The google.ai docs/code is annoying to parse
    try:
        yield
    except AssertionError as e:
        logger.debug("The Gemini prompt is invalid.")
        raise BadAPIRequestError(str(e)) from e
    except APIError as e:
        logger.debug("Gemini failed to generate content.")
        raise BadAPIRequestError(str(e)) from e
    except ValueError as e:
        logger.debug("Gemini did not return a simple text response.")
        raise BadAPIRequestError(str(e)) from e
    except AttributeError as e:
        logger.debug("There is an error with the Gemini prompt or processing code: {}.", str(e))
        raise BadAPIRequestError(str(e)) from e
    except httpx.RemoteProtocolError as e:
        logger.debug(str(e))
        raise TransientLanguageModelError("httpx.RemoteProtocolError") from e
    except (BadAPIRequestError, TransientLanguageModelError, MissingAPIKeyError):
        # we already raised this error ourselves earlier, so we don't need to mark it as unknown
        raise
    except Exception as e:
        # we catch TransientLanguageModelError later to retry it, but we still want to log it so it's not silent
        log_exception(
            e,
            "Failed to generate output from Gemini, unknown error of type {type_name}",
            type_name=type(e).__name__,
        )
        raise TransientLanguageModelError("Unknown error") from e


R = TypeVar("R")


def fmap(fn: Callable[[T], R], values: T | None) -> R | None:
    if values is None:
        return None
    return fn(values)


class GeminiAPI(LanguageModelAPI):
    model_name: GeminiModelName = GeminiModelName.GEMINI_2_5_FLASH
    is_conversational: bool = True

    count_tokens_cache_path: Path | None = None

    @field_validator("model_name")  # pyre-ignore[56]: pyre doesn't understand pydantic
    @classmethod
    def validate_model_name(cls, v: str) -> str:
        if v not in GEMINI_MODEL_INFO_BY_NAME:
            raise LanguageModelInvalidModelNameError(v, cls.__name__, list(GEMINI_MODEL_INFO_BY_NAME))
        return v

    @property
    def model_info(self) -> ModelInfo:
        return GEMINI_MODEL_INFO_BY_NAME[self.model_name]

    def _get_client(self) -> genai.Client:
        api_key = get_secret("GOOGLE_API_KEY")
        if not api_key:
            raise MissingAPIKeyError("GOOGLE_API_KEY environment variable is not set")
        return genai.Client(api_key=api_key)

    async def _call_api(
        self,
        prompt: str,
        params: LanguageModelGenerationParams,
        network_failure_count: int = 0,
    ) -> CostedLanguageModelResponse:
        # TODO: check if this is still true
        assert params.count == 1, "Gemini only supports a single completion"
        messages = convert_prompt_to_gemini_messages(prompt)
        with _gemini_exception_manager():
            client = self._get_client()
            generation_config = GenerateContentConfig(
                temperature=params.temperature,
                candidate_count=params.count,
                stop_sequences=fmap(lambda x: [x], params.stop),
                max_output_tokens=params.max_tokens,
                thinking_config=fmap(
                    lambda thinking: ThinkingConfig(
                        thinking_budget=thinking.max_tokens,
                        include_thoughts=thinking.output_thinking,
                    ),
                    params.thinking,
                ),
            )

            api_result: GenerateContentResponse = await client.aio.models.generate_content(
                model=self.model_info.model_name,
                contents=messages,
                config=generation_config,
            )

            prompt_tokens = self.count_tokens(prompt)

            if (
                api_result.prompt_feedback is not None
                and api_result.prompt_feedback.block_reason is not None
                and api_result.prompt_feedback.block_reason != BlockedReason.BLOCKED_REASON_UNSPECIFIED
            ):
                logger.warning(
                    f"Gemini blocked output: {messages=}, {api_result.prompt_feedback.block_reason=}, {api_result.prompt_feedback.safety_ratings=}"
                )
                return create_costed_language_model_response_for_single_result(
                    text="",
                    prompt_tokens=prompt_tokens,
                    completion_tokens=0,
                    stop_reason=ResponseStopReason.NONE,
                    network_failure_count=network_failure_count,
                    dollars_used=self.calculate_cost(prompt_tokens, 0),  # guestimate of cost,
                )

            if _is_flagged_as_unsafe(api_result) or _is_flagged_as_recitation(api_result):
                block_reason = fmap(lambda x: x.block_reason, api_result.prompt_feedback)
                safety_ratings = (
                    api_result.prompt_feedback.safety_ratings if api_result.prompt_feedback is not None else None
                )
                logger.warning(
                    "Gemini flagged output: block_reason={block_reason}, safety_ratings={safety_ratings}",
                    block_reason=block_reason,
                    safety_ratings=safety_ratings,
                )
                return create_costed_language_model_response_for_single_result(
                    text="",
                    prompt_tokens=prompt_tokens,
                    completion_tokens=0,
                    stop_reason=ResponseStopReason.CONTENT_FILTER,
                    network_failure_count=network_failure_count,
                    dollars_used=self.calculate_cost(prompt_tokens, 0),
                )

            candidate = only_and_not_none(api_result.candidates)
            finish_reason = candidate.finish_reason
            parsed_finish_reason = (
                _GEMINI_STOP_REASON_TO_STOP_REASON[finish_reason]
                if finish_reason is not None
                else ResponseStopReason.NONE
            )

            if finish_reason not in [FinishReason.MAX_TOKENS, FinishReason.STOP]:
                block_reason = fmap(lambda x: x.block_reason, api_result.prompt_feedback)
                safety_ratings = fmap(lambda x: x.safety_ratings, api_result.prompt_feedback)
                logger.warning(
                    f"Gemini did not return a simple text response, {block_reason=}, {safety_ratings=}, {finish_reason=}, {candidate.safety_ratings=}"
                )
                return create_costed_language_model_response_for_single_result(
                    text="",
                    prompt_tokens=prompt_tokens,
                    completion_tokens=0,
                    stop_reason=parsed_finish_reason,
                    network_failure_count=network_failure_count,
                    dollars_used=self.calculate_cost(prompt_tokens, 0),
                )

            text = api_result.text

            thoughts_list = fmap(
                lambda content: fmap(
                    lambda parts: [part.text for part in parts if part.thought],
                    content.parts,
                ),
                candidate.content,
            )
            if not thoughts_list:
                thoughts = None
            else:
                thoughts = only(thoughts_list)

            if text is None:
                if finish_reason == FinishReason.MAX_TOKENS and generation_config.thinking_config is not None:
                    raise BadAPIRequestError(
                        "Gemini ran out of tokens while thinking and did not return a text response"
                    )
                logger.warning("Non-simple-text response: {}", api_result)
                raise BadAPIRequestError("Gemini did not return a simple text response (text is None)")

            prompt_tokens = (
                api_result.usage_metadata.prompt_token_count
                if api_result.usage_metadata is not None and api_result.usage_metadata.prompt_token_count is not None
                else self.count_tokens(prompt)
            )

            thought_tokens = (
                api_result.usage_metadata.thoughts_token_count
                if api_result.usage_metadata is not None and api_result.usage_metadata.thoughts_token_count is not None
                else 0
            )

            output_tokens = (
                api_result.usage_metadata.candidates_token_count
                if api_result.usage_metadata is not None
                and api_result.usage_metadata.candidates_token_count is not None
                else self.count_tokens(text)
            )

            completion_tokens = output_tokens + thought_tokens

            dollars_used = self.calculate_cost(prompt_tokens, completion_tokens)
            logger.trace(text)
            logger.trace("Dollars used: {}", dollars_used)
            return create_costed_language_model_response_for_single_result(
                text=text,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                stop_reason=parsed_finish_reason,
                network_failure_count=network_failure_count,
                dollars_used=dollars_used,
                thoughts=fmap(
                    lambda x: ThoughtResponse(text=x, completion_tokens=thought_tokens),
                    thoughts,
                ),
            )

    def _get_api_stream(
        self,
        prompt: str,
        params: LanguageModelGenerationParams,
    ) -> AsyncGenerator[LanguageModelStreamEvent, None]:
        # TODO Implement streaming support (?)
        raise NotImplementedError()

    # TODO: these are the same as in anthropic_api.py. it might be good to refactor so that both AnthropicAPI and GeminiAPI inherit from a class LanguageModelAPIWithCountTokens which has these methods
    def get_count_tokens_response_cache(self) -> AsyncCache[CachedCountTokensResponse]:
        if self.count_tokens_cache_path is None:
            raise UnsetCachePathError()
        return AsyncCache(self.count_tokens_cache_path, CachedCountTokensResponse)

    async def check_count_tokens_cache(self, cache_key: str) -> CountTokensResponse | None:
        return await self.check_cache_core(self.get_count_tokens_response_cache, cache_key)

    async def _get_from_count_tokens_cache(
        self, frame: FrameType | None
    ) -> tuple[str | None, CountTokensResponse | None]:
        return await self._get_from_cache_core(frame, lambda cr: cr, self.check_count_tokens_cache)

    async def count_tokens_api(self, text: str, is_caching_enabled: bool) -> int | None:
        """Call the count_tokens api to get a definitive token count. May be fragile and is definitely slow."""

        self.assert_caching_enabled_if_offline(is_caching_enabled)

        frame: FrameType | None = None
        if is_caching_enabled:
            frame = inspect.currentframe()

        cache_key: str | None = None
        if is_caching_enabled:
            cache_key, cached_response = await self._get_from_count_tokens_cache(frame)

            if cached_response is not None:
                return cached_response.input_tokens

        self.assert_not_offline_if_cache_miss(text)

        with _gemini_exception_manager():
            client = self._get_client()
            response = client.models.count_tokens(model=self.model_info.model_name, contents=text)

            total_tokens = response.total_tokens
            if total_tokens is None:
                raise TransientLanguageModelError("Gemini did not return a valid token count")

            result = CachedCountTokensResponse(
                response=CountTokensResponse(
                    input_tokens=total_tokens,
                    cached_content_token_count=response.cached_content_token_count,
                ),
                inputs=(
                    CountTokensInputs(model=self.model_info.model_name, prompt=text) if self.is_caching_inputs else None
                ),
            )

            if is_caching_enabled:
                assert cache_key is not None
                async with self.get_count_tokens_response_cache() as cache:
                    await cache.set(cache_key, result)

            return total_tokens
