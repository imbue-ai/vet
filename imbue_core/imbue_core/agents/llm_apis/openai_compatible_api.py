import math
from contextlib import contextmanager
from typing import AsyncGenerator
from typing import Iterator

import httpx
from loguru import logger
from openai import AsyncOpenAI
from openai import AsyncStream
from openai import InternalServerError
from openai import NotGiven
from openai._exceptions import APIConnectionError
from openai._exceptions import BadRequestError
from openai._exceptions import RateLimitError
from openai.types.chat import ChatCompletion

from imbue_core.agents.llm_apis.api_utils import convert_prompt_to_openai_messages
from imbue_core.agents.llm_apis.constants import approximate_token_count
from imbue_core.agents.llm_apis.data_types import CachingInfo
from imbue_core.agents.llm_apis.data_types import CostedLanguageModelResponse
from imbue_core.agents.llm_apis.data_types import LanguageModelGenerationParams
from imbue_core.agents.llm_apis.data_types import LanguageModelResponse
from imbue_core.agents.llm_apis.data_types import LanguageModelResponseUsage
from imbue_core.agents.llm_apis.data_types import ResponseStopReason
from imbue_core.agents.llm_apis.errors import BadAPIRequestError
from imbue_core.agents.llm_apis.errors import PromptTooLongError
from imbue_core.agents.llm_apis.errors import TransientLanguageModelError
from imbue_core.agents.llm_apis.language_model_api import LanguageModelAPI
from imbue_core.agents.llm_apis.models import ModelInfo
from imbue_core.agents.llm_apis.openai_data_types import OpenAICachingInfo
from imbue_core.agents.llm_apis.stream import LanguageModelStreamDeltaEvent
from imbue_core.agents.llm_apis.stream import LanguageModelStreamEndEvent
from imbue_core.agents.llm_apis.stream import LanguageModelStreamEvent
from imbue_core.agents.llm_apis.stream import LanguageModelStreamStartEvent
from imbue_core.frozen_utils import FrozenDict
from imbue_core.frozen_utils import FrozenMapping
from imbue_core.itertools import only
from imbue_core.secrets_utils import get_secret

_OPENAI_COMPATIBLE_STOP_REASON_TO_STOP_REASON: FrozenMapping[
    str, ResponseStopReason
] = FrozenDict(
    {
        "stop": ResponseStopReason.END_TURN,
        "length": ResponseStopReason.MAX_TOKENS,
        "tool_calls": ResponseStopReason.TOOL_CALLS,
        "function_call": ResponseStopReason.FUNCTION_CALL,
        "content_filter": ResponseStopReason.CONTENT_FILTER,
        "None": ResponseStopReason.NONE,
    }
)


# TODO: Should the pre-defined OpenAI model class inherit from this?
class OpenAICompatibleAPI(LanguageModelAPI):
    model_name: str
    base_url: str = "https://api.openai.com/v1"
    api_key_env: str = "OPENAI_API_KEY"
    context_window: int | None = None
    max_output_tokens: int | None = None
    is_conversational: bool = True
    presence_penalty: float = 0.0
    # this shouldn't really ever even be used, but just in case
    stop_token_log_probability: float = math.log(0.9999)

    @property
    def model_info(self) -> ModelInfo:
        if self.context_window is None or self.max_output_tokens is None:
            raise ValueError(
                "Must provide context_window and max_output_tokens, or subclass must override model_info"
            )
        return ModelInfo(
            model_name=self.model_name,
            cost_per_input_token=0.0,
            cost_per_output_token=0.0,
            max_input_tokens=self.context_window,
            max_output_tokens=self.max_output_tokens,
            rate_limit_req=None,
        )

    def _get_client(self) -> AsyncOpenAI:
        api_key = get_secret(self.api_key_env) if self.api_key_env else ""
        if not api_key:
            api_key = "not-required"
            logger.debug("API key not set, attempting to use API without key.")

        return AsyncOpenAI(
            api_key=api_key,
            base_url=self.base_url,
        )

    @contextmanager
    def _exception_handler(self, prompt: str) -> Iterator[None]:
        try:
            yield
        except BadRequestError as e:
            if e.code == "context_length_exceeded":
                prompt_len = self.count_tokens(prompt)
                max_prompt_len = self.model_info.max_input_tokens
                logger.debug(
                    "PromptTooLongError max_prompt_len={max_prompt_len} prompt_len={prompt_len}",
                    max_prompt_len=max_prompt_len,
                    prompt_len=prompt_len,
                )
                raise PromptTooLongError(prompt_len, max_prompt_len) from e
            logger.debug("BadAPIRequestError {e}", e=e)
            raise BadAPIRequestError(str(e)) from e
        except APIConnectionError as e:
            logger.debug("API connection error: {e}", e=e)
            raise TransientLanguageModelError("APIConnectionError") from e
        except RateLimitError as e:
            if e.code == "insufficient_quota":
                raise
            logger.debug("Rate limited: {e}", e=e)
            raise TransientLanguageModelError("RateLimitError") from e
        except httpx.RemoteProtocolError as e:
            logger.debug("httpx.RemoteProtocolError {e}", e=e)
            raise TransientLanguageModelError("httpx.RemoteProtocolError") from e
        except InternalServerError as e:
            logger.debug("InternalServerError {e}", e=e)
            raise TransientLanguageModelError("InternalServerError") from e

    async def _call_api(
        self,
        prompt: str,
        params: LanguageModelGenerationParams,
        network_failure_count: int = 0,
    ) -> CostedLanguageModelResponse:
        messages = convert_prompt_to_openai_messages(prompt)

        with self._exception_handler(prompt):
            client = self._get_client()

            temperature: NotGiven | float = params.temperature

            api_result = await client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                max_completion_tokens=params.max_tokens,
                n=params.count,
                temperature=temperature,
                stream=False,
                seed=params.seed,
                stop=params.stop,
                presence_penalty=self.presence_penalty,
            )
            assert isinstance(api_result, ChatCompletion)

            usage = api_result.usage
            if usage is not None:
                completion_tokens = usage.completion_tokens
                prompt_tokens = usage.prompt_tokens
                cached_tokens = (
                    usage.prompt_tokens_details.cached_tokens
                    if usage.prompt_tokens_details is not None
                    else 0
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

            results = self._parse_response(
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

        with self._exception_handler(prompt):
            client = self._get_client()

            temperature: NotGiven | float = params.temperature

            api_result = await client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                max_completion_tokens=params.max_tokens,
                n=1,
                temperature=temperature,
                stop=params.stop,
                seed=params.seed,
                stream=True,
                stream_options={"include_usage": True},
                presence_penalty=self.presence_penalty,
            )
            assert isinstance(api_result, AsyncStream)

            yield LanguageModelStreamStartEvent()

            usage = None
            finish_reason: str | None = None
            async for chunk in api_result:
                if hasattr(chunk, "usage") and chunk.usage is not None:
                    usage = chunk.usage
                    continue

                if chunk.choices:
                    assert (
                        len(chunk.choices) == 1
                    ), "Currently only count=1 supported for streaming API."
                    data = only(chunk.choices)
                    delta = data.delta.content
                    if delta is not None:
                        yield LanguageModelStreamDeltaEvent(delta=delta)
                    if data.finish_reason:
                        finish_reason = str(data.finish_reason)

            stop_reason = _OPENAI_COMPATIBLE_STOP_REASON_TO_STOP_REASON.get(
                str(finish_reason), ResponseStopReason.NONE
            )
            if params.stop is not None and stop_reason == ResponseStopReason.END_TURN:
                yield LanguageModelStreamDeltaEvent(delta=params.stop)

            if usage is not None:
                completion_tokens = usage.completion_tokens
                prompt_tokens = usage.prompt_tokens
                dollars_used = self.calculate_cost(prompt_tokens, completion_tokens)
                cached_tokens = (
                    usage.prompt_tokens_details.cached_tokens
                    if usage.prompt_tokens_details is not None
                    else 0
                ) or 0
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
        return approximate_token_count(text)

    def _parse_response(
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
            stop_reason = _OPENAI_COMPATIBLE_STOP_REASON_TO_STOP_REASON.get(
                str(data.finish_reason), ResponseStopReason.NONE
            )
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
