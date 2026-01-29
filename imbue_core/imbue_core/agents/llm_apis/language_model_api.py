import abc
import asyncio
import contextvars
import hashlib
import inspect
import os
import random
from pathlib import Path
from types import FrameType
from typing import AsyncGenerator
from typing import Awaitable
from typing import Callable
from typing import TypeVar
from typing import final
from uuid import UUID
from uuid import uuid4

import anyio
from loguru import logger

from imbue_core.agents.llm_apis.constants import approximate_token_count
from imbue_core.agents.llm_apis.data_types import CachedCostedLanguageModelResponse
from imbue_core.agents.llm_apis.data_types import CachedCostedModelResponse
from imbue_core.agents.llm_apis.data_types import CachingInfo
from imbue_core.agents.llm_apis.data_types import CostedLanguageModelResponse
from imbue_core.agents.llm_apis.data_types import CountTokensResponse
from imbue_core.agents.llm_apis.data_types import InputsT
from imbue_core.agents.llm_apis.data_types import LanguageModelCompleteInputs
from imbue_core.agents.llm_apis.data_types import LanguageModelGenerationParams
from imbue_core.agents.llm_apis.data_types import LanguageModelResponse
from imbue_core.agents.llm_apis.data_types import LanguageModelStreamInputs
from imbue_core.agents.llm_apis.data_types import ModelResponseT
from imbue_core.agents.llm_apis.errors import LanguageModelRetryLimitError
from imbue_core.agents.llm_apis.errors import PromptTooLongError
from imbue_core.agents.llm_apis.errors import TransientLanguageModelError
from imbue_core.agents.llm_apis.errors import UnsetCachePathError
from imbue_core.agents.llm_apis.models import ModelInfo
from imbue_core.agents.llm_apis.stream import LanguageModelStreamCallback
from imbue_core.agents.llm_apis.stream import LanguageModelStreamEvent
from imbue_core.agents.llm_apis.stream import PromptDebuggingCallback
from imbue_core.agents.llm_apis.stream import SettleSpendCallback
from imbue_core.agents.llm_apis.stream import StreamedLanguageModelResponse
from imbue_core.agents.llm_apis.stream import UpdateCacheCallback
from imbue_core.agents.llm_apis.stream import get_cached_response_stream
from imbue_core.agents.primitives.resource_limits import PaymentAuthorization
from imbue_core.agents.primitives.resource_limits import get_global_resource_limits
from imbue_core.async_utils import sync
from imbue_core.caching import AsyncCache
from imbue_core.cattrs_serialization import serialize_to_json
from imbue_core.pydantic_serialization import MutableModel

# Context variable to disable caching.
IS_LLM_CACHING_DISABLED_GLOBALLY = contextvars.ContextVar(
    "is_llm_caching_disabled_globally", default=False
)
# Context variable for injecting a default seed which will become part of the LLM cache key.
LLM_GLOBAL_DEFAULT_SEED = contextvars.ContextVar("llm_global_default_seed", default=0)

# Maximum number of retries for network failures.
MAX_RETRIES = 5


EXCLUDED_CACHE_KEY_ARGS = ["self", "is_caching_enabled", "call_id"]


def _create_base_cache_key_from_frame(frame: FrameType) -> str:
    """Create a cache key from the args of a function by passing its frame."""
    args, _, _, values = inspect.getargvalues(frame)
    return "|".join(
        f"{arg}={values[arg]}" for arg in args if arg not in EXCLUDED_CACHE_KEY_ARGS
    )


CostedResponseT = TypeVar(
    "CostedResponseT", bound=CostedLanguageModelResponse | CountTokensResponse
)
FinalResponseT = TypeVar(
    "FinalResponseT",
    bound=CostedLanguageModelResponse
    | StreamedLanguageModelResponse
    | CountTokensResponse,
)


class LanguageModelAPI(abc.ABC, MutableModel):
    model_name: str
    cache_path: Path | None
    is_caching_inputs: bool = False
    is_running_offline: bool = False
    is_conversational: bool = False
    is_using_logprobs: bool = False

    # retry/timeout values
    retry_sleep_time: float = 2.0
    retry_backoff_factor: float = 3.0
    retry_jitter_factor: float = 0.5

    # TODO: Consider storing the model_config here as well.

    @property
    @abc.abstractmethod
    def model_info(self) -> ModelInfo: ...

    def get_response_cache(self) -> AsyncCache[CachedCostedLanguageModelResponse]:
        if self.cache_path is None:
            raise UnsetCachePathError()
        return AsyncCache(self.cache_path, CachedCostedLanguageModelResponse)

    def _create_cache_key(self, base_key: str) -> str:
        object_cache_attributes = self.model_dump(
            exclude={
                "cache_path",
                "count_tokens_cache_path",
                "base_url",
                "api_key_env",
                "context_window",
                "max_output_tokens",
            }
        )
        # have to reset the offline key to the same value so that that doesnt invalidate the cache
        object_cache_attributes["is_running_offline"] = True
        object_cache_attributes["__name__"] = self.__class__.__name__
        base_key_md5 = hashlib.md5(base_key.encode()).hexdigest()
        object_cache_attributes["__request_key_md5__"] = base_key_md5
        return serialize_to_json(object_cache_attributes)

    async def check_cache_core(
        self,
        cache_getter: Callable[
            [], AsyncCache[CachedCostedModelResponse[InputsT, ModelResponseT]]
        ],
        cache_key: str,
    ) -> ModelResponseT | None:
        async with cache_getter() as cache:
            cached_result = await cache.get(cache_key)

        if cached_result is not None:
            if cached_result.error:
                if cached_result.error.startswith(PromptTooLongError.__name__):
                    raise PromptTooLongError.from_string(cached_result.error)
                raise Exception(
                    f"Unknown cached result error type: {cached_result.error}"
                )
            assert cached_result.response is not None
            return cached_result.response
        return None

    async def check_cache(self, cache_key: str) -> CostedLanguageModelResponse | None:
        return await self.check_cache_core(self.get_response_cache, cache_key)

    async def _get_auth(
        self, prompt: str, max_tokens: int | None
    ) -> PaymentAuthorization | None:
        global_resource_limits = get_global_resource_limits()
        if global_resource_limits is not None:
            prompt_tokens = self.count_tokens(prompt)
            completion_tokens = (
                max_tokens
                if max_tokens is not None
                else self.get_max_completion_size_in_tokens()
            )
            upper_bound_cost_estimate = self.estimate_cost(
                prompt_tokens, completion_tokens
            )
            assert global_resource_limits is not None
            auth: PaymentAuthorization = await global_resource_limits.authorize_spend(
                upper_bound_cost_estimate,
                debug_info={
                    "model_name": self.model_name,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                },
            )
            return auth

        if "PYTEST_CURRENT_TEST" not in os.environ:
            logger.warning(
                "You are trying to call a language model from outside of a hammer with no global resource limits set. That is a bad idea because the spend will not be restricted, and you may end up accidentally spending much more than you expected."
            )
        return None

    async def _settle_spend(
        self, auth: PaymentAuthorization, dollars_used: float
    ) -> None:
        global_resource_limits = get_global_resource_limits()
        assert global_resource_limits is not None
        await global_resource_limits.settle_spend(auth, dollars_used)
        return None

    def assert_caching_enabled_if_offline(self, is_caching_enabled: bool) -> None:
        if self.is_running_offline:
            assert is_caching_enabled, "Caching must be enabled when running offline"

    def assert_not_offline_if_cache_miss(self, prompt: str) -> None:
        max_n_chars = 50
        prompt_stub = prompt[:max_n_chars] + (
            "..." if len(prompt) > max_n_chars else ""
        )
        assert (
            not self.is_running_offline
        ), f"Running offline but did not have a cached response for this query! Prompt: {prompt_stub}"

    async def complete(
        self,
        prompt: str,
        params: LanguageModelGenerationParams,
        is_caching_enabled: bool = True,
    ) -> tuple[LanguageModelResponse, ...]:
        call_id = uuid4()
        logger.trace(
            "[{call_id}] Calling complete with params: {params} and is_caching_enabled={is_caching_enabled} and {prompt}",
            call_id=call_id,
            params=params,
            is_caching_enabled=is_caching_enabled,
            prompt=prompt[:40],
        )
        if _complete_concurrency_hook_fn is not None:
            await _complete_concurrency_hook_fn(self)

        is_caching_enabled_with_override = (
            is_caching_enabled and not IS_LLM_CACHING_DISABLED_GLOBALLY.get()
        )
        if params.seed is None:
            params = params.evolve(params.ref().seed, LLM_GLOBAL_DEFAULT_SEED.get())

        return await self._complete(
            prompt,
            params,
            is_caching_enabled=is_caching_enabled_with_override,
            call_id=call_id,
        )

    complete_sync = sync(complete)

    async def complete_with_usage(
        self,
        prompt: str,
        params: LanguageModelGenerationParams,
        is_caching_enabled: bool = True,
    ) -> CostedLanguageModelResponse:
        call_id = uuid4()
        if _complete_concurrency_hook_fn is not None:
            await _complete_concurrency_hook_fn(self)

        is_caching_enabled_with_override = (
            is_caching_enabled and not IS_LLM_CACHING_DISABLED_GLOBALLY.get()
        )
        if params.seed is None:
            params = params.evolve(params.ref().seed, LLM_GLOBAL_DEFAULT_SEED.get())

        return await self._complete_with_usage(
            prompt,
            params,
            is_caching_enabled=is_caching_enabled_with_override,
            call_id=call_id,
        )

    complete_with_usage_sync = sync(complete_with_usage)

    async def _complete_with_usage(
        self,
        prompt: str,
        params: LanguageModelGenerationParams,
        is_caching_enabled: bool,
        call_id: UUID,
    ) -> CostedLanguageModelResponse:
        self._warn_if_no_stop_condition_and_not_conversational(params)
        self.assert_caching_enabled_if_offline(is_caching_enabled)

        frame: FrameType | None = None
        if is_caching_enabled:
            frame = inspect.currentframe()

        costed_response_to_output: Callable[
            [CostedLanguageModelResponse], CostedLanguageModelResponse
        ] = lambda cr: cr

        cache_key: str | None = None
        if is_caching_enabled:
            cache_key, cached_response = await self._get_from_cache(
                frame, costed_response_to_output
            )

            if cached_response is not None:
                return cached_response

        self.assert_not_offline_if_cache_miss(prompt)

        auth = await self._get_auth(prompt, params.max_tokens)

        sleep_time = self.retry_sleep_time
        last_error_msg: str | None = None
        for network_failure_count in range(MAX_RETRIES):
            try:
                api_inputs = LanguageModelCompleteInputs(
                    prompt=prompt,
                    params=params,
                    network_failure_count=network_failure_count,
                )
                response = await self._call_api_one_arg(api_inputs)
                if is_caching_enabled:
                    assert cache_key is not None
                    result = CachedCostedLanguageModelResponse(
                        response=response,
                        inputs=api_inputs if self.is_caching_inputs else None,
                    )
                    async with self.get_response_cache() as cache:
                        await cache.set(cache_key, result)

                if auth is not None:
                    await self._settle_spend(auth, response.usage.dollars_used)

                return response

            except PromptTooLongError as e:
                logger.trace(
                    "[{call_id}] Prompt too long error in model {model_name}",
                    call_id=call_id,
                    model_name=self.model_name,
                )
                if is_caching_enabled:
                    assert cache_key is not None
                    async with self.get_response_cache() as cache:
                        await cache.set(
                            cache_key,
                            CachedCostedLanguageModelResponse(error=e.to_string()),
                        )
                raise
            except TransientLanguageModelError as e:
                last_error_msg = str(e)
                if network_failure_count < MAX_RETRIES - 1:
                    if self.retry_jitter_factor > 0:
                        max_jitter = sleep_time * self.retry_jitter_factor
                        sleep_time += random.uniform(-max_jitter / 2, max_jitter / 2)
                    logger.debug(
                        f"Transient language model error ({str(e)}) in model {self.model_name}, retrying with sleep time {sleep_time} seconds..."
                    )
                    await asyncio.sleep(sleep_time)
                    sleep_time *= self.retry_backoff_factor
        raise LanguageModelRetryLimitError(
            last_error_msg or "Unknown error (this should not happen)"
        )

    async def _complete(
        self,
        prompt: str,
        params: LanguageModelGenerationParams,
        is_caching_enabled: bool,
        call_id: UUID,
    ) -> tuple[LanguageModelResponse, ...]:
        # Delegate to _complete_with_usage and extract just the responses
        # May have more than count responses cached, so just return first count responses
        costed_response = await self._complete_with_usage(
            prompt, params, is_caching_enabled, call_id
        )
        return costed_response.responses[: params.count]

    @final
    async def _call_api_one_arg(
        self, api_inputs: LanguageModelCompleteInputs
    ) -> CostedLanguageModelResponse:
        """Delegates to the abstract method _call_api, which must be implemented by subclasses."""
        return await self._call_api(
            prompt=api_inputs.prompt,
            params=api_inputs.params,
            network_failure_count=api_inputs.network_failure_count,
        )

    @abc.abstractmethod
    async def _call_api(
        self,
        prompt: str,
        params: LanguageModelGenerationParams,
        # this is used to track how many times we've retried due to network failures, since we want the return type to contain that information
        network_failure_count: int = 0,
    ) -> CostedLanguageModelResponse:
        """If defined, the stop sequence should be part of the sequence (if it was actually generated)"""

    async def stream(
        self,
        prompt: str,
        is_caching_enabled: bool = True,
        params: LanguageModelGenerationParams = LanguageModelGenerationParams(),
    ) -> StreamedLanguageModelResponse:
        if params.seed is None:
            params = params.evolve(params.ref().seed, LLM_GLOBAL_DEFAULT_SEED.get())

        is_caching_enabled_with_override = (
            is_caching_enabled and not IS_LLM_CACHING_DISABLED_GLOBALLY.get()
        )

        return await self._stream(
            prompt=prompt,
            is_caching_enabled=is_caching_enabled_with_override,
            params=params,
        )

    async def _stream(
        self,
        prompt: str,
        is_caching_enabled: bool,
        params: LanguageModelGenerationParams,
    ) -> StreamedLanguageModelResponse:
        assert (
            params.count == 1
        ), "Stream API currently only supports count=1 due to limitations of some APIs."

        self._warn_if_no_stop_condition_and_not_conversational(params)
        self.assert_caching_enabled_if_offline(is_caching_enabled)

        frame: FrameType | None = None
        if is_caching_enabled:
            frame = inspect.currentframe()

        # Note it's technically possible multiple responses cached for given prompt (e.g. from call to complete())
        # for now we just return first one
        costed_response_to_output = lambda cr: StreamedLanguageModelResponse(
            get_cached_response_stream(cr),
            network_failure_count=0,
            completion_callbacks=(),
        )
        cache_key: str | None = None
        if is_caching_enabled:
            cache_key, cached_response = await self._get_from_cache(
                frame, costed_response_to_output
            )

            if cached_response is not None:
                return cached_response

        self.assert_not_offline_if_cache_miss(prompt)

        auth = await self._get_auth(prompt, params.max_tokens)

        sleep_time = self.retry_sleep_time
        last_error_msg: str | None = None
        for network_failure_count in range(MAX_RETRIES):
            # Loop until success or an exception is raised
            try:
                api_inputs = LanguageModelStreamInputs(prompt=prompt, params=params)
                api_stream = await self._get_api_stream_one_arg(api_inputs)
                callbacks: list[LanguageModelStreamCallback] = []
                if is_caching_enabled:
                    assert cache_key is not None
                    cache = self.get_response_cache()
                    callbacks.append(
                        UpdateCacheCallback(
                            key=cache_key,
                            cache=cache,
                            api_inputs=api_inputs if self.is_caching_inputs else None,
                        )
                    )
                llm_debug_output_folder = os.getenv("LLM_DEBUG_PATH", None)
                if llm_debug_output_folder is not None:
                    output_path = anyio.Path(llm_debug_output_folder) / f"{uuid4()}.txt"
                    # write out the prompt (helps with debugging so we can see when things blow up)
                    await output_path.write_text(prompt)
                    # overwrite the file with the prompt and completion when done
                    callbacks.append(
                        PromptDebuggingCallback(prompt=prompt, output_path=output_path)
                    )

                if auth is not None:
                    callbacks.append(SettleSpendCallback(auth=auth))

                return StreamedLanguageModelResponse(
                    api_stream,
                    network_failure_count=network_failure_count,
                    completion_callbacks=callbacks,
                )

            except PromptTooLongError as e:
                if is_caching_enabled:
                    assert cache_key is not None
                    async with self.get_response_cache() as cache:
                        await cache.set(
                            cache_key,
                            CachedCostedLanguageModelResponse(error=e.to_string()),
                        )
                raise
            except TransientLanguageModelError as e:
                last_error_msg = str(e)
                if network_failure_count < MAX_RETRIES - 1:
                    if self.retry_jitter_factor > 0:
                        sleep_time += random.uniform(
                            0, sleep_time * self.retry_jitter_factor
                        )
                    logger.debug(
                        f"Transient language model error ({str(e)}) in model {self.model_name}, retrying with sleep time {sleep_time} seconds..."
                    )
                    await asyncio.sleep(sleep_time)
                    sleep_time *= self.retry_backoff_factor
        raise LanguageModelRetryLimitError(
            last_error_msg or "Unknown error (this should not happen)"
        )

    @final
    async def _get_api_stream_one_arg(
        self, api_inputs: LanguageModelStreamInputs
    ) -> AsyncGenerator[LanguageModelStreamEvent, None]:
        """Delegates to the abstract method _get_api_stream, which must be implemented by subclasses."""
        return self._get_api_stream(prompt=api_inputs.prompt, params=api_inputs.params)

    @abc.abstractmethod
    def _get_api_stream(
        self,
        prompt: str,
        params: LanguageModelGenerationParams,
    ) -> AsyncGenerator[LanguageModelStreamEvent, None]:
        """If defined, the stop sequence should be part of the sequence (if it was actually generated)"""

    def _warn_if_no_stop_condition_and_not_conversational(
        self, params: LanguageModelGenerationParams
    ) -> None:
        if (
            params.stop is None and params.max_tokens is None
        ) and not self.is_conversational:
            logger.debug(
                "Did not specify either `max_tokens` or `stop`, and this is not a conversational model. The completion will go until the entire context window is filled. Preferably you don't do this, because it is fairly inefficient."
            )

    async def _get_from_cache_core(
        self,
        frame: FrameType | None,
        costed_response_to_output: Callable[[CostedResponseT], FinalResponseT],
        cache_checker: Callable[[str], Awaitable[CostedResponseT | None]],
    ) -> tuple[str | None, FinalResponseT | None]:
        cache_key: str | None

        cache_key, costed_response = await self._get_costed_response_from_frame_core(
            cache_checker, frame
        )

        if costed_response is not None:
            return cache_key, costed_response_to_output(costed_response)
        return cache_key, None

    async def _get_from_cache(
        self,
        frame: FrameType | None,
        costed_response_to_output: Callable[
            [CostedLanguageModelResponse], FinalResponseT
        ],
    ) -> tuple[str | None, FinalResponseT | None]:
        return await self._get_from_cache_core(
            frame, costed_response_to_output, self.check_cache
        )

    async def _get_costed_response_from_frame_core(
        self,
        cache_checker: Callable[[str], Awaitable[CostedResponseT | None]],
        frame: FrameType | None,
    ) -> tuple[str, CostedResponseT | None]:
        assert frame is not None
        cache_key = self._create_cache_key(_create_base_cache_key_from_frame(frame))
        costed_response = await cache_checker(cache_key)
        return cache_key, costed_response

    def count_tokens(self, text: str) -> int:
        # this is VERY approximate, but many of the child models have nothing, so...
        return approximate_token_count(text)

    def basic_calculate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (
            prompt_tokens * self.model_info.cost_per_input_token
            + completion_tokens * self.model_info.cost_per_output_token
        )

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Estimate the cost of a request before it has been made. Doesn't use any caching info."""
        return self.basic_calculate_cost(prompt_tokens, completion_tokens)

    def calculate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        caching_info: CachingInfo | None = None,
    ) -> float:
        """Overridden by subclasses which have more complex cost calculations, such as if caching is used."""
        logger.info(
            f"no calculate_cost implemented for {self.model_name}; using basic_calculate_cost",
            model_name=self.model_name,
        )
        return self.basic_calculate_cost(prompt_tokens, completion_tokens)

    def get_max_completion_size_in_tokens(self) -> int:
        if self.model_info.max_output_tokens is not None:
            return self.model_info.max_output_tokens
        # assume max output is just the context window size
        return self.model_info.max_input_tokens

    def get_max_prompt_size_in_tokens(self) -> int:
        return self.model_info.max_input_tokens

    def get_context_window_size_in_tokens(self) -> int:
        return (
            self.get_max_completion_size_in_tokens()
            + self.get_max_prompt_size_in_tokens()
        )


COMPLETE_CONCURRENCY_HOOK_FN = Callable[[LanguageModelAPI], Awaitable[None]] | None
_complete_concurrency_hook_fn: COMPLETE_CONCURRENCY_HOOK_FN = None


def set_language_model_api_complete_concurrency_hook(
    hook_fn: COMPLETE_CONCURRENCY_HOOK_FN,
) -> None:
    global _complete_concurrency_hook_fn
    _complete_concurrency_hook_fn = hook_fn
