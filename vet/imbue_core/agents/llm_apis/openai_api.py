import asyncio
import enum
import re
from collections import defaultdict
from contextlib import contextmanager
from functools import lru_cache
from typing import AsyncGenerator
from typing import Iterator
from typing import Mapping

import httpx
import tiktoken
from loguru import logger
from openai import AsyncStream
from openai import InternalServerError
from openai import NOT_GIVEN
from openai import NotGiven
from openai._client import AsyncOpenAI
from openai._exceptions import APIConnectionError
from openai._exceptions import BadRequestError
from openai._exceptions import RateLimitError
from openai.types.chat import ChatCompletion
from pydantic.functional_validators import field_validator

from vet.imbue_core.agents.llm_apis.api_utils import convert_prompt_to_openai_messages
from vet.imbue_core.agents.llm_apis.data_types import CachingInfo
from vet.imbue_core.agents.llm_apis.data_types import CostedLanguageModelResponse
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelGenerationParams
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelResponse
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelResponseUsage
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelResponseWithLogits
from vet.imbue_core.agents.llm_apis.data_types import ResponseStopReason
from vet.imbue_core.agents.llm_apis.data_types import TokenProbability
from vet.imbue_core.agents.llm_apis.errors import BadAPIRequestError
from vet.imbue_core.agents.llm_apis.errors import LanguageModelInvalidModelNameError
from vet.imbue_core.agents.llm_apis.errors import MissingAPIKeyError
from vet.imbue_core.agents.llm_apis.errors import PromptTooLongError
from vet.imbue_core.agents.llm_apis.errors import TransientLanguageModelError
from vet.imbue_core.agents.llm_apis.models import ModelInfo
from vet.imbue_core.agents.llm_apis.openai_compatible_api import OpenAICompatibleAPI
from vet.imbue_core.agents.llm_apis.openai_compatible_api import _OPENAI_COMPATIBLE_STOP_REASON_TO_STOP_REASON
from vet.imbue_core.agents.llm_apis.openai_data_types import OpenAICachingInfo
from vet.imbue_core.agents.llm_apis.stream import LanguageModelStreamDeltaEvent
from vet.imbue_core.agents.llm_apis.stream import LanguageModelStreamEndEvent
from vet.imbue_core.agents.llm_apis.stream import LanguageModelStreamEvent
from vet.imbue_core.agents.llm_apis.stream import LanguageModelStreamStartEvent
from vet.imbue_core.frozen_utils import FrozenDict
from vet.imbue_core.frozen_utils import FrozenMapping
from vet.imbue_core.itertools import only
from vet.imbue_core.secrets_utils import get_secret

FINE_TUNED_GPT4O_MINI_2024_07_18_PREFIX = "ft:gpt-4o-mini-2024-07-18"
FINE_TUNED_GPT4O_2024_08_06_PREFIX = "ft:gpt-4o-2024-08-06"


class OpenAIModelName(enum.StrEnum):
    GPT_4_1 = "gpt-4.1"
    GPT_4_1_MINI = "gpt-4.1-mini"
    O3 = "o3"
    O3_MINI = "o3-mini"
    O4_MINI = "o4-mini"
    GPT_5 = "gpt-5"
    GPT_5_MINI = "gpt-5-mini"
    GPT_5_1 = "gpt-5.1"
    GPT_5_2 = "gpt-5.2"


# Using Tier 5 rate limits
# https://platform.openai.com/settings/organization/limits

OPENAI_MODEL_INFO_BY_NAME: FrozenMapping[OpenAIModelName, ModelInfo] = FrozenDict(
    {
        OpenAIModelName.GPT_4_1: ModelInfo(
            model_name=str(OpenAIModelName.GPT_4_1),
            cost_per_input_token=2 / 1_000_000,
            cost_per_output_token=8 / 1_000_000,
            max_input_tokens=1_047_576,
            max_output_tokens=32_768,
            rate_limit_req=10000 / 60,  # 10000 RPM = 166.67 RPS
        ),
        OpenAIModelName.GPT_4_1_MINI: ModelInfo(
            model_name=str(OpenAIModelName.GPT_4_1_MINI),
            cost_per_input_token=0.4 / 1_000_000,
            cost_per_output_token=1.6 / 1_000_000,
            max_input_tokens=1_047_576,
            max_output_tokens=32_768,
            rate_limit_req=30000 / 60,  # 30000 RPM = 500 RPS
        ),
        OpenAIModelName.O3: ModelInfo(
            model_name=str(OpenAIModelName.O3),
            cost_per_input_token=2 / 1_000_000,
            cost_per_output_token=8 / 1_000_000,
            max_input_tokens=200_000,
            max_output_tokens=100_000,
            rate_limit_req=10000 / 60,  # 10000 RPM = 166.67 RPS
        ),
        OpenAIModelName.O3_MINI: ModelInfo(
            model_name=str(OpenAIModelName.O3_MINI),
            cost_per_input_token=1.1 / 1_000_000,
            cost_per_output_token=4.4 / 1_000_000,
            max_input_tokens=200_000,
            max_output_tokens=100_000,
            rate_limit_req=30000 / 60,  # 30000 RPM = 500 RPS
        ),
        OpenAIModelName.O4_MINI: ModelInfo(
            model_name=str(OpenAIModelName.O4_MINI),
            cost_per_input_token=1.1 / 1_000_000,
            cost_per_output_token=4.4 / 1_000_000,
            max_input_tokens=200_000,
            max_output_tokens=100_000,
            rate_limit_req=30000 / 60,  # 30000 RPM = 500 RPS
        ),
        OpenAIModelName.GPT_5: ModelInfo(
            model_name=str(OpenAIModelName.GPT_5),
            cost_per_input_token=1.25 / 1_000_000,
            cost_per_output_token=10 / 1_000_000,
            max_input_tokens=400_000,
            max_output_tokens=128_000,
            rate_limit_req=15000 / 60,  # 15000 RPM = 250 RPS
        ),
        OpenAIModelName.GPT_5_MINI: ModelInfo(
            model_name=str(OpenAIModelName.GPT_5_MINI),
            cost_per_input_token=0.25 / 1_000_000,
            cost_per_output_token=2.00 / 1_000_000,
            max_input_tokens=400_000,
            max_output_tokens=128_000,
            rate_limit_req=30000 / 60,  # 30000 RPM = 500 RPS
        ),
        OpenAIModelName.GPT_5_1: ModelInfo(
            model_name=str(OpenAIModelName.GPT_5_1),
            cost_per_input_token=1.25 / 1_000_000,
            cost_per_output_token=10 / 1_000_000,
            max_input_tokens=400_000,
            max_output_tokens=128_000,
            rate_limit_req=15000 / 60,  # 15000 RPM = 250 RPS
        ),
        OpenAIModelName.GPT_5_2: ModelInfo(
            model_name=str(OpenAIModelName.GPT_5_2),
            cost_per_input_token=1.75 / 1_000_000,
            cost_per_output_token=14 / 1_000_000,
            max_input_tokens=400_000,
            max_output_tokens=128_000,
            rate_limit_req=15000 / 60,  # 15000 RPM = 250 RPS
        ),
    }
)


# Pricing for fine-tuned models taken from here: https://platform.openai.com/docs/pricing
def get_model_info(model_name: OpenAIModelName) -> ModelInfo:
    # Check for the family of fine-tuned models.
    if model_name.startswith(FINE_TUNED_GPT4O_MINI_2024_07_18_PREFIX):
        return ModelInfo(
            model_name=str(model_name),
            cost_per_input_token=0.3 / 1_000_000,
            cost_per_output_token=1.2 / 1_000_000,
            max_input_tokens=128_000,
            max_output_tokens=16_384,
            rate_limit_req=30000 / 60,  # 30000 RPM = 500 RPS (same as base model)
        )
    if model_name.startswith(FINE_TUNED_GPT4O_2024_08_06_PREFIX):
        return ModelInfo(
            model_name=str(model_name),
            cost_per_input_token=3.75 / 1_000_000,
            cost_per_output_token=15.0 / 1_000_000,
            max_input_tokens=128_000,
            max_output_tokens=16_384,
            rate_limit_req=10000 / 60,  # 10000 RPM = 166.67 RPS (same as base model)
        )
    # Otherwise, return the model info for the base model.
    return OPENAI_MODEL_INFO_BY_NAME[model_name]


_CAPACITY_SEMAPHOR_BY_MODEL_NAME: Mapping[OpenAIModelName, asyncio.Semaphore] = defaultdict(
    lambda: asyncio.Semaphore(20),
)


def _get_capacity_semaphor(model_name: OpenAIModelName) -> asyncio.Semaphore:
    # Fine-tuned models share rate limits with the base model.
    # Note: fine-tuned model prefixes fall through to the defaultdict default.
    return _CAPACITY_SEMAPHOR_BY_MODEL_NAME[model_name]


def is_openai_reasoning_model(model_name: str) -> bool:
    return model_name in (
        OpenAIModelName.O3,
        OpenAIModelName.O3_MINI,
        OpenAIModelName.O4_MINI,
        OpenAIModelName.GPT_5,
        OpenAIModelName.GPT_5_MINI,
        OpenAIModelName.GPT_5_1,
        OpenAIModelName.GPT_5_2,
    )


def is_fine_tuned_openai_model(model_name: OpenAIModelName) -> bool:
    return model_name.value.startswith(FINE_TUNED_GPT4O_MINI_2024_07_18_PREFIX) or model_name.value.startswith(
        FINE_TUNED_GPT4O_2024_08_06_PREFIX
    )


_OPENAI_COMPLETION_ERROR_PATTERN = re.compile(
    r".*This model's maximum context length is (\d+) tokens, however you requested (\d+) tokens \((\d+) in your prompt; (\d+) for the completion\). Please reduce your prompt; or completion length.*"
)

_OPENAI_STOP_REASON_TO_STOP_REASON = _OPENAI_COMPATIBLE_STOP_REASON_TO_STOP_REASON


@lru_cache(maxsize=1)
def get_openai_tokenizer(model_name: str) -> tiktoken.Encoding:
    """Get the appropriate tiktoken tokenizer for an OpenAI model.

    Args:
        model_name: The OpenAI model name (e.g., "gpt-4o-2024-08-06").

    Returns:
        The tiktoken Encoding for the model.
    """
    if model_name.startswith("gpt-4"):
        fixed_model_name = "gpt-4"
    elif model_name.startswith("gpt-3.5"):
        fixed_model_name = "gpt-3.5"
    else:
        # Just default to `gpt-4o` for now, since this seems to be the most recent tokenizer
        # and we are only using it for estimating token usage
        fixed_model_name = "gpt-4o"
    return tiktoken.encoding_for_model(fixed_model_name)


def count_openai_tokens(text: str, model_name: str) -> int:
    return len(get_openai_tokenizer(model_name).encode(text, disallowed_special=()))


@contextmanager
def _openai_exception_manager() -> Iterator[None]:
    """Simple context manager for parsing OpenAI API exceptions."""
    try:
        yield
    except BadRequestError as e:
        error_text_match = _OPENAI_COMPLETION_ERROR_PATTERN.search(str(e))
        if error_text_match is not None:
            max_prompt_len = int(error_text_match.group(1))
            prompt_len = int(error_text_match.group(2))
            logger.debug(
                "PromptTooLongError max_prompt_len={max_prompt_len} prompt_len={prompt_len}",
                max_prompt_len=max_prompt_len,
                prompt_len=prompt_len,
            )
            raise PromptTooLongError(prompt_len, max_prompt_len) from e
        logger.debug("BadAPIRequestError {e}", e=e)
        raise BadAPIRequestError(str(e)) from e
    except APIConnectionError as e:
        logger.debug("Rate limited? Received APIConnectionError {e}", e=e)
        raise TransientLanguageModelError("APIConnectionError") from e
    except RateLimitError as e:
        if e.code == "insufficient_quota":
            raise
        logger.debug("Rate limited? {e}", e=e)
        raise TransientLanguageModelError("RateLimitError") from e
    except httpx.RemoteProtocolError as e:
        logger.debug("httpx.RemoteProtocolError {e}", e=e)
        raise TransientLanguageModelError("httpx.RemoteProtocolError") from e
    except InternalServerError as e:
        logger.debug("InternalServerError {e}", e=e)
        raise TransientLanguageModelError("InternalServerError") from e


class OpenAIChatAPI(OpenAICompatibleAPI):
    model_name: OpenAIModelName = OpenAIModelName.GPT_4_1

    @field_validator("model_name")  # pyre-ignore[56]: pyre doesn't understand pydantic
    @classmethod
    def validate_model_name(cls, v: str) -> str:
        if v not in OPENAI_MODEL_INFO_BY_NAME:
            raise LanguageModelInvalidModelNameError(v, cls.__name__, list(OPENAI_MODEL_INFO_BY_NAME))
        return v

    @property
    def model_info(self) -> ModelInfo:
        return get_model_info(self.model_name)

    def _get_client(self) -> AsyncOpenAI:
        api_key = get_secret("OPENAI_API_KEY")
        if not api_key:
            raise MissingAPIKeyError("OPENAI_API_KEY environment variable is not set")
        return AsyncOpenAI(  # pyre-ignore[16]: pyre doesn't understand the auto-generated openai._client
            api_key=api_key
        )

    async def _call_api(
        self,
        prompt: str,
        params: LanguageModelGenerationParams,
        network_failure_count: int = 0,
    ) -> CostedLanguageModelResponse:
        messages = convert_prompt_to_openai_messages(prompt)
        with _openai_exception_manager():
            client = self._get_client()

            is_reasoning_model = is_openai_reasoning_model(self.model_name)

            top_logprobs: NotGiven | int
            if self.is_using_logprobs:
                assert not is_reasoning_model, "Logprobs are not supported for reasoning models."
                top_logprobs = 5
            else:
                top_logprobs = NOT_GIVEN

            temperature: NotGiven | float = NOT_GIVEN if is_reasoning_model else params.temperature

            async with _get_capacity_semaphor(self.model_name):
                api_result = await client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,  # type: ignore
                    max_completion_tokens=params.max_tokens,
                    n=params.count,
                    temperature=temperature,
                    stream=False,
                    seed=params.seed,
                    stop=params.stop,
                    presence_penalty=self.presence_penalty,
                    logprobs=self.is_using_logprobs,
                    top_logprobs=top_logprobs,
                )
                assert isinstance(api_result, ChatCompletion)

            usage = api_result.usage
            if usage is not None:
                completion_tokens = usage.completion_tokens
                prompt_tokens = usage.prompt_tokens
                cached_tokens = (
                    usage.prompt_tokens_details.cached_tokens if usage.prompt_tokens_details is not None else 0
                ) or 0
                caching_info = CachingInfo(
                    read_from_cache=cached_tokens,
                    provider_specific_data=OpenAICachingInfo(),
                )
            else:
                completion_tokens = 0
                prompt_tokens = self.count_tokens(prompt)
                cached_tokens = None
                caching_info = None

            results: tuple[LanguageModelResponse | LanguageModelResponseWithLogits, ...]
            if self.is_using_logprobs:
                results = self._parse_response_with_logprobs(
                    api_result,
                    prompt_tokens=prompt_tokens,
                    stop=params.stop,
                    network_failure_count=network_failure_count,
                )
            else:
                results = self._parse_response_without_logprobs(
                    api_result,
                    prompt_tokens=prompt_tokens,
                    stop=params.stop,
                    network_failure_count=network_failure_count,
                )

            logger.trace("text: {text}", text=results[0].text)
            dollars_used = self.calculate_cost(prompt_tokens, completion_tokens)
            logger.trace("dollars used: {dollars_used}", dollars_used=dollars_used)
            return CostedLanguageModelResponse(
                usage=LanguageModelResponseUsage(
                    prompt_tokens_used=prompt_tokens,
                    completion_tokens_used=completion_tokens,
                    dollars_used=dollars_used,
                    caching_info=caching_info,
                ),
                responses=tuple(results),
            )

    async def _get_api_stream(
        self,
        prompt: str,
        params: LanguageModelGenerationParams,
    ) -> AsyncGenerator[LanguageModelStreamEvent, None]:
        messages = convert_prompt_to_openai_messages(prompt)
        with _openai_exception_manager():
            client = self._get_client()

            is_reasoning_model = is_openai_reasoning_model(self.model_name)
            temperature: NotGiven | float = NOT_GIVEN if is_reasoning_model else params.temperature

            async with _get_capacity_semaphor(self.model_name):
                api_result = await client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,  # type: ignore
                    max_completion_tokens=params.max_tokens,
                    n=1,
                    temperature=temperature,
                    stop=params.stop,
                    seed=params.seed,
                    stream=True,
                    stream_options={"include_usage": True},
                    presence_penalty=self.presence_penalty,
                    logprobs=False,  # not used when streaming
                    top_logprobs=NOT_GIVEN,  # only allowed when logprobs=True
                )
            assert isinstance(api_result, AsyncStream)

            yield LanguageModelStreamStartEvent()

            usage = None
            finish_reason: str | None = None
            async for chunk in api_result:
                if hasattr(chunk, "usage") and chunk.usage is not None:
                    # final chunk containing usage info after all streaming is done
                    usage = chunk.usage
                    continue

                if chunk.choices:
                    assert len(chunk.choices) == 1, "Currently only count=1 supported for streaming API."
                    data = only(chunk.choices)
                    delta = data.delta.content
                    if delta is not None:
                        yield LanguageModelStreamDeltaEvent(delta=delta)
                    if data.finish_reason:
                        finish_reason = str(data.finish_reason)

            stop_reason = _OPENAI_STOP_REASON_TO_STOP_REASON[str(finish_reason)]
            # Note, OpenAI API treats end turn and stop sequence the same
            # Here we assume it is stop sequence if user has specified a stop sequence
            if params.stop is not None and stop_reason == ResponseStopReason.END_TURN:
                yield LanguageModelStreamDeltaEvent(delta=params.stop)

            if usage is not None:
                completion_tokens = usage.completion_tokens
                prompt_tokens = usage.prompt_tokens
                dollars_used = self.calculate_cost(prompt_tokens, completion_tokens)
                cached_tokens = usage.prompt_tokens_details.cached_tokens
                logger.trace(
                    "Used this many cached read tokens: {cached_tokens}",
                    cached_tokens=cached_tokens,
                )
                caching_info = CachingInfo(
                    read_from_cache=cached_tokens,
                    provider_specific_data=OpenAICachingInfo(),
                )
            else:
                completion_tokens = -1
                prompt_tokens = -1
                dollars_used = -1
                caching_info = None
            logger.trace("dollars used: {dollars_used}", dollars_used=dollars_used)

            yield LanguageModelStreamEndEvent(
                usage=LanguageModelResponseUsage(
                    prompt_tokens_used=prompt_tokens,
                    completion_tokens_used=completion_tokens,
                    dollars_used=dollars_used,
                    caching_info=caching_info,
                ),
                stop_reason=stop_reason,
            )

    def count_tokens(self, text: str) -> int:
        return count_openai_tokens(text, self.model_name)

    def _parse_response_without_logprobs(
        self,
        response: ChatCompletion,
        prompt_tokens: int,
        stop: str | None,
        network_failure_count: int,
    ) -> tuple[LanguageModelResponse, ...]:
        results = []
        for data in response.choices:
            assert data.message.content is not None
            text = data.message.content
            token_count = self.count_tokens(text) + prompt_tokens
            stop_reason = _OPENAI_STOP_REASON_TO_STOP_REASON[str(data.finish_reason)]
            # Note, OpenAI API treats end turn and stop sequence the same
            # Here we assume it is stop sequence if user has specified a stop sequence
            if stop is not None and stop_reason == ResponseStopReason.END_TURN:
                text += stop
            result = LanguageModelResponse(
                text=text,
                token_count=token_count,
                stop_reason=stop_reason,
                network_failure_count=network_failure_count,
            )
            results.append(result)
        return tuple(results)

    def _parse_response_with_logprobs(
        self,
        response: ChatCompletion,
        prompt_tokens: int,
        stop: str | None,
        network_failure_count: int,
    ) -> tuple[LanguageModelResponseWithLogits, ...]:
        results = []
        for data in response.choices:
            assert data.message.content is not None
            logprobs = data.logprobs
            assert logprobs is not None
            logprobs_content = logprobs.content
            assert logprobs_content is not None
            text = data.message.content

            token_probabilities = []
            for logprob_token_entry in logprobs_content:
                top_logprobs = logprob_token_entry.top_logprobs
                top_entries = [
                    TokenProbability(
                        token=top_logprob_obj.token,
                        log_probability=top_logprob_obj.logprob,
                        is_stop=False,
                    )
                    for top_logprob_obj in top_logprobs
                ]
                selected_entry = TokenProbability(
                    token=logprob_token_entry.token,
                    log_probability=logprob_token_entry.logprob,
                    is_stop=False,
                )
                if selected_entry in top_entries:
                    top_entries.remove(selected_entry)
                token_probabilities.append(tuple([selected_entry] + top_entries))

            stop_reason = _OPENAI_STOP_REASON_TO_STOP_REASON[str(data.finish_reason)]

            # Note, OpenAI API treats end turn and stop sequence the same
            # Here we assume it is stop sequence if user has specified a stop sequence
            if stop is not None and stop_reason == ResponseStopReason.END_TURN:
                text += stop
                token_probabilities.append(
                    tuple(
                        [
                            TokenProbability(
                                token=stop,
                                log_probability=self.stop_token_log_probability,
                                is_stop=True,
                            )
                        ]
                    )
                )
            result = LanguageModelResponseWithLogits(
                text=text,
                token_probabilities=tuple(token_probabilities),
                token_count=len(logprobs_content) + prompt_tokens,
                stop_reason=stop_reason,
                network_failure_count=network_failure_count,
            )
            results.append(result)
        return tuple(results)
