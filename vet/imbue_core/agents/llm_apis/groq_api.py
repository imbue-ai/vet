import asyncio
import enum
import math
from contextlib import contextmanager
from typing import AsyncGenerator
from typing import Final
from typing import Iterator
from typing import Mapping

import httpx
from groq import APIConnectionError
from groq import APIError
from groq import AsyncGroq
from groq import AsyncStream
from groq import BadRequestError
from groq import RateLimitError
from groq.types.chat import ChatCompletion
from loguru import logger
from pydantic.functional_validators import field_validator

from vet.imbue_core.agents.llm_apis.api_utils import convert_prompt_to_openai_messages
from vet.imbue_core.agents.llm_apis.data_types import CostedLanguageModelResponse
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelGenerationParams
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelResponse
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelResponseUsage
from vet.imbue_core.agents.llm_apis.data_types import ResponseStopReason
from vet.imbue_core.agents.llm_apis.errors import BadAPIRequestError
from vet.imbue_core.agents.llm_apis.errors import LanguageModelInvalidModelNameError
from vet.imbue_core.agents.llm_apis.errors import MissingAPIKeyError
from vet.imbue_core.agents.llm_apis.errors import PromptTooLongError
from vet.imbue_core.agents.llm_apis.errors import TransientLanguageModelError
from vet.imbue_core.agents.llm_apis.language_model_api import LanguageModelAPI
from vet.imbue_core.agents.llm_apis.models import ModelInfo
from vet.imbue_core.agents.llm_apis.stream import LanguageModelStreamDeltaEvent
from vet.imbue_core.agents.llm_apis.stream import LanguageModelStreamEndEvent
from vet.imbue_core.agents.llm_apis.stream import LanguageModelStreamEvent
from vet.imbue_core.agents.llm_apis.stream import LanguageModelStreamStartEvent
from vet.imbue_core.frozen_utils import FrozenDict
from vet.imbue_core.frozen_utils import FrozenMapping
from vet.imbue_core.itertools import only
from vet.imbue_core.secrets_utils import get_secret

# note: we require that these model versions are explicit, just like the rest of our dependencies
# the reason is that these models are actually now mostly deterministic, and it is much easier to debug if we know what model was used
# also, there's no need to troll yourself by wondering why results have improved (or gotten worse) when you dont realized that the version has shifted under you
# if you want to use an upgraded model, just upgrade the model to the key displayed on the website
# please do NOT set these back to the generic model names!


# TODO: there are likely more models to add
class GroqSupportedModelName(enum.StrEnum):
    GROQ_GEMMA2_9B_IT = "groq/gemma2-9b-it"
    GROQ_LLAMA3_70B_8192 = "groq/llama3-70b-8192"
    GROQ_LLAMA3_8B_8192 = "groq/llama3-8b-8192"
    GROQ_LLAMA_3_3_70B_SPECDEC = "groq/llama-3.3-70b-specdec"
    GROQ_MIXTRAL_8X7B_32768 = "groq/mixtral-8x7b-32768"
    GROQ_LLAMA_3_3_70B_VERSATILE = "groq/llama-3.3-70b-versatile"
    GROQ_LLAMA_3_1_8B_INSTANT = "groq/llama-3.1-8b-instant"
    GROQ_LLAMA_3_2_1B_PREVIEW = "groq/llama-3.2-1b-preview"
    GROQ_LLAMA_3_2_3B_PREVIEW = "groq/llama-3.2-3b-preview"


# Rate limits for Groq models based on custom rate limits for our organization.
# See here https://console.groq.com/dashboard/limits (requires login, use your Google account)

GROQ_MODEL_INFO_BY_NAME: FrozenMapping[GroqSupportedModelName, ModelInfo] = FrozenDict(
    {
        GroqSupportedModelName.GROQ_GEMMA2_9B_IT: ModelInfo(
            model_name=str(GroqSupportedModelName.GROQ_GEMMA2_9B_IT),
            cost_per_input_token=0.20 / 1_000_000,
            cost_per_output_token=0.20 / 1_000_000,
            max_input_tokens=8192,
            max_output_tokens=None,
            rate_limit_req=30 / 60,  # 30 RPM = 0.50 RPS
        ),
        GroqSupportedModelName.GROQ_LLAMA3_70B_8192: ModelInfo(
            model_name=str(GroqSupportedModelName.GROQ_LLAMA3_70B_8192),
            cost_per_input_token=0.59 / 1_000_000,
            cost_per_output_token=0.79 / 1_000_000,
            max_input_tokens=8192,
            max_output_tokens=None,
            rate_limit_req=30 / 60,  # 30 RPM = 0.50 RPS
        ),
        GroqSupportedModelName.GROQ_LLAMA3_8B_8192: ModelInfo(
            model_name=str(GroqSupportedModelName.GROQ_LLAMA3_8B_8192),
            cost_per_input_token=0.05 / 1_000_000,
            cost_per_output_token=0.08 / 1_000_000,
            max_input_tokens=8192,
            max_output_tokens=None,
            rate_limit_req=30 / 60,  # 30 RPM = 0.50 RPS
        ),
        GroqSupportedModelName.GROQ_LLAMA_3_3_70B_SPECDEC: ModelInfo(
            model_name=str(GroqSupportedModelName.GROQ_LLAMA_3_3_70B_SPECDEC),
            cost_per_input_token=0.59 / 1_000_000,
            cost_per_output_token=0.99 / 1_000_000,
            max_input_tokens=8192,
            max_output_tokens=None,
            rate_limit_req=30 / 60,  # 30 RPM = 0.50 RPS
        ),
        GroqSupportedModelName.GROQ_MIXTRAL_8X7B_32768: ModelInfo(
            model_name=str(GroqSupportedModelName.GROQ_MIXTRAL_8X7B_32768),
            cost_per_input_token=0.24 / 1_000_000,
            cost_per_output_token=0.24 / 1_000_000,
            max_input_tokens=32768,
            max_output_tokens=None,
            rate_limit_req=30 / 60,  # 30 RPM = 0.50 RPS
        ),
        GroqSupportedModelName.GROQ_LLAMA_3_3_70B_VERSATILE: ModelInfo(
            model_name=str(GroqSupportedModelName.GROQ_LLAMA_3_3_70B_VERSATILE),
            cost_per_input_token=0.59 / 1_000_000,
            cost_per_output_token=0.79 / 1_000_000,
            max_input_tokens=128_000,
            max_output_tokens=None,
            rate_limit_req=30 / 60,  # 30 RPM = 0.50 RPS
        ),
        GroqSupportedModelName.GROQ_LLAMA_3_1_8B_INSTANT: ModelInfo(
            model_name=str(GroqSupportedModelName.GROQ_LLAMA_3_1_8B_INSTANT),
            cost_per_input_token=0.05 / 1_000_000,
            cost_per_output_token=0.08 / 1_000_000,
            max_input_tokens=128_000,
            max_output_tokens=None,
            rate_limit_req=30 / 60,  # 30 RPM = 0.50 RPS
        ),
        GroqSupportedModelName.GROQ_LLAMA_3_2_1B_PREVIEW: ModelInfo(
            model_name=str(GroqSupportedModelName.GROQ_LLAMA_3_2_1B_PREVIEW),
            cost_per_input_token=0.04 / 1_000_000,
            cost_per_output_token=0.04 / 1_000_000,
            max_input_tokens=128_000,
            max_output_tokens=None,
            rate_limit_req=30 / 60,  # 30 RPM = 0.50 RPS
        ),
        GroqSupportedModelName.GROQ_LLAMA_3_2_3B_PREVIEW: ModelInfo(
            model_name=str(GroqSupportedModelName.GROQ_LLAMA_3_2_3B_PREVIEW),
            cost_per_input_token=0.06 / 1_000_000,
            cost_per_output_token=0.06 / 1_000_000,
            max_input_tokens=128_000,
            max_output_tokens=None,
            rate_limit_req=30 / 60,  # 30 RPM = 0.50 RPS
        ),
    }
)


def get_model_info(model_name: GroqSupportedModelName) -> ModelInfo:
    return GROQ_MODEL_INFO_BY_NAME[model_name]


_CAPACITY_SEMAPHOR_BY_MODEL_NAME: Mapping[str, asyncio.Semaphore] = {
    GroqSupportedModelName.GROQ_GEMMA2_9B_IT: asyncio.Semaphore(100),
    GroqSupportedModelName.GROQ_LLAMA3_70B_8192: asyncio.Semaphore(100),
    GroqSupportedModelName.GROQ_LLAMA3_8B_8192: asyncio.Semaphore(100),
    GroqSupportedModelName.GROQ_LLAMA_3_3_70B_SPECDEC: asyncio.Semaphore(100),
    GroqSupportedModelName.GROQ_MIXTRAL_8X7B_32768: asyncio.Semaphore(100),
    GroqSupportedModelName.GROQ_LLAMA_3_3_70B_VERSATILE: asyncio.Semaphore(100),
    GroqSupportedModelName.GROQ_LLAMA_3_1_8B_INSTANT: asyncio.Semaphore(100),
    GroqSupportedModelName.GROQ_LLAMA_3_2_1B_PREVIEW: asyncio.Semaphore(100),
    GroqSupportedModelName.GROQ_LLAMA_3_2_3B_PREVIEW: asyncio.Semaphore(100),
}


def _get_capacity_semaphor(model_name: str) -> asyncio.Semaphore:
    return _CAPACITY_SEMAPHOR_BY_MODEL_NAME[model_name]


# ref: https://github.com/groq/groq-python/blob/b74ce9e301115520c744e18425653a4c783cb6f5/src/groq/types/chat/chat_completion_chunk.py#L86
_GROQ_STOP_REASON_TO_STOP_REASON: Final[FrozenMapping[str, ResponseStopReason]] = FrozenDict(
    {
        # Groq copies OpenAI and treats stop due to natural stop point and provided stop sequence the same
        "stop": ResponseStopReason.END_TURN,
        "length": ResponseStopReason.MAX_TOKENS,
        "tool_calls": ResponseStopReason.TOOL_CALLS,
        "function_call": ResponseStopReason.FUNCTION_CALL,
        "content_filter": ResponseStopReason.CONTENT_FILTER,
    }
)


@contextmanager
def _groq_exception_manager() -> Iterator[None]:
    """Simple context manager for parsing groq exceptions mostly based on how we parse OpenAI API exceptions."""
    try:
        yield
    except BadRequestError as e:
        logger.debug("BadAPIRequestError {}", e)
        raise BadAPIRequestError(str(e)) from e
    except APIConnectionError as e:
        logger.debug("Rate limited? Received APIConnectionError {}", e)
        raise TransientLanguageModelError("APIConnectionError") from e
    except RateLimitError as e:
        logger.debug("Rate limited? {}", e)
        raise TransientLanguageModelError("RateLimitError") from e
    except httpx.RemoteProtocolError as e:
        logger.debug("{}", e)
        raise TransientLanguageModelError("httpx.RemoteProtocolError") from e
    except APIError as e:
        if e.body["code"] == "context_length_exceeded":  # type: ignore
            # TODO: eventually fix elsewhere, since this doesn't actually give you any information in the body...
            raise PromptTooLongError(prompt_len=1, max_prompt_len=1)
        raise TransientLanguageModelError("APIError") from e


class GroqChatAPI(LanguageModelAPI):
    model_name: GroqSupportedModelName = GroqSupportedModelName.GROQ_LLAMA3_8B_8192
    is_conversational: bool = True
    presence_penalty: float = 0.0
    # this shouldn't really ever even be used, but just in case
    stop_token_log_probability: float = math.log(0.9999)

    @field_validator("model_name")  # pyre-ignore[56]: pyre doesn't understand pydantic
    @classmethod
    def validate_model_name(cls, v: str) -> str:
        if v not in GROQ_MODEL_INFO_BY_NAME:
            raise LanguageModelInvalidModelNameError(v, cls.__name__, list(GROQ_MODEL_INFO_BY_NAME))
        return v

    @property
    def model_info(self) -> ModelInfo:
        return GROQ_MODEL_INFO_BY_NAME[self.model_name]

    @property
    def external_model_name(self) -> str:
        return self.model_name.replace("groq/", "")

    def _get_client(self) -> AsyncGroq:
        api_key = get_secret("GROQ_API_KEY")
        if not api_key:
            raise MissingAPIKeyError("GROQ_API_KEY environment variable is not set")
        return AsyncGroq(api_key=api_key)

    async def _call_api(
        self,
        prompt: str,
        params: LanguageModelGenerationParams,
        network_failure_count: int = 0,
    ) -> CostedLanguageModelResponse:
        with _groq_exception_manager():
            messages = convert_prompt_to_openai_messages(prompt)
            client = self._get_client()
            async with _get_capacity_semaphor(self.model_name):
                # logger.info("Open requests: {}", semaphor._value)
                api_result = await client.chat.completions.create(
                    model=self.external_model_name,
                    messages=messages,  # type: ignore
                    max_tokens=params.max_tokens,
                    n=params.count,
                    temperature=params.temperature,
                    stop=params.stop,
                    logprobs=False,
                    seed=params.seed,
                    stream=False,
                    presence_penalty=self.presence_penalty,
                )
                assert isinstance(api_result, ChatCompletion)

            results = []
            for data in api_result.choices:
                assert data.message.content is not None

                assert data.logprobs is not None and data.logprobs.content is not None
                text = data.message.content

                stop_reason = _GROQ_STOP_REASON_TO_STOP_REASON[str(data.finish_reason)]

                # Note, like OpenAI, Groq treats end turn and stop sequence the same
                # Here we assume it is stop sequence if user has specified a stop sequence
                if params.stop is not None and stop_reason == ResponseStopReason.END_TURN:
                    text += params.stop
                result = LanguageModelResponse(
                    text=text,
                    token_count=0,
                    stop_reason=stop_reason,
                    network_failure_count=network_failure_count,
                )
                results.append(result)

            logger.trace("text: " + results[0].text)
            if api_result.usage is not None:
                completion_tokens = api_result.usage.completion_tokens
                prompt_tokens = api_result.usage.prompt_tokens
            else:
                completion_tokens = 0
                prompt_tokens = 0
            dollars_used = self.calculate_cost(prompt_tokens, completion_tokens)
            logger.trace("dollars used: {}", dollars_used)
            return CostedLanguageModelResponse(
                usage=LanguageModelResponseUsage(
                    prompt_tokens_used=prompt_tokens,
                    completion_tokens_used=completion_tokens,
                    dollars_used=dollars_used,
                ),
                responses=tuple(results),
            )

    async def _get_api_stream(
        self,
        prompt: str,
        params: LanguageModelGenerationParams,
    ) -> AsyncGenerator[LanguageModelStreamEvent, None]:
        with _groq_exception_manager():
            messages = convert_prompt_to_openai_messages(prompt)
            client = self._get_client()
            async with _get_capacity_semaphor(self.model_name):
                api_result = await client.chat.completions.create(
                    model=self.external_model_name,
                    messages=messages,  # type: ignore
                    max_tokens=params.max_tokens,
                    n=1,
                    temperature=params.temperature,
                    stop=params.stop,
                    logprobs=False,
                    seed=params.seed,
                    stream=True,
                    # This field is currently unsupported by the groq API
                    # stream_options={"include_usage": True},
                    presence_penalty=self.presence_penalty,
                )
            assert isinstance(api_result, AsyncStream)
            logger.debug("API response status code: {}", api_result.response.status_code)

            yield LanguageModelStreamStartEvent()

            usage = None
            finish_reason: str | None = None
            async for chunk in api_result:
                if chunk.choices:
                    assert len(chunk.choices) == 1, "Currently only count=1 supported for streaming API."
                    data = only(chunk.choices)
                    delta = data.delta.content
                    if delta is not None:
                        yield LanguageModelStreamDeltaEvent(delta=delta)
                    if data.finish_reason:
                        finish_reason = str(data.finish_reason)

            stop_reason = _GROQ_STOP_REASON_TO_STOP_REASON[str(finish_reason)]
            # Note, Open API treats end turn and stop sequence the same TODO: check if groq is the same
            # Here we assume it is stop sequence if user has specified a stop sequence
            if params.stop is not None and stop_reason == ResponseStopReason.END_TURN:
                yield LanguageModelStreamDeltaEvent(delta=params.stop)

            if usage is not None:
                completion_tokens = usage.completion_tokens
                prompt_tokens = usage.prompt_tokens
                dollars_used = self.calculate_cost(prompt_tokens, completion_tokens)
            else:
                completion_tokens = -1
                prompt_tokens = -1
                dollars_used = -1
            logger.trace("dollars used: {}", dollars_used)

            yield LanguageModelStreamEndEvent(
                usage=LanguageModelResponseUsage(
                    prompt_tokens_used=prompt_tokens,
                    completion_tokens_used=completion_tokens,
                    dollars_used=dollars_used,
                ),
                stop_reason=stop_reason,
            )
