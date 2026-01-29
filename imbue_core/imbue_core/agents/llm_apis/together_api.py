import asyncio
import enum
import math
from collections import defaultdict
from contextlib import contextmanager
from typing import AsyncGenerator
from typing import Final
from typing import Iterable
from typing import Iterator
from typing import Mapping
from typing import cast

from loguru import logger
from pydantic.functional_validators import field_validator
from together import AsyncTogether
from together.abstract.api_requestor import APIRequestor
from together.abstract.api_requestor import AioHTTPSession
from together.error import APIConnectionError
from together.error import APIError
from together.error import AuthenticationError
from together.error import InvalidRequestError
from together.error import RateLimitError
from together.error import ServiceUnavailableError
from together.together_response import TogetherResponse
from together.types import TogetherRequest
from together.types.chat_completions import ChatCompletionResponse

from imbue_core.agents.llm_apis.data_types import CostedLanguageModelResponse
from imbue_core.agents.llm_apis.data_types import LanguageModelGenerationParams
from imbue_core.agents.llm_apis.data_types import LanguageModelResponseUsage
from imbue_core.agents.llm_apis.data_types import LanguageModelResponseWithLogits
from imbue_core.agents.llm_apis.data_types import ResponseStopReason
from imbue_core.agents.llm_apis.data_types import TokenProbability
from imbue_core.agents.llm_apis.errors import BadAPIRequestError
from imbue_core.agents.llm_apis.errors import LanguageModelInvalidModelNameError
from imbue_core.agents.llm_apis.errors import MissingAPIKeyError
from imbue_core.agents.llm_apis.errors import TransientLanguageModelError
from imbue_core.agents.llm_apis.language_model_api import LanguageModelAPI
from imbue_core.agents.llm_apis.models import ModelInfo
from imbue_core.agents.llm_apis.stream import LanguageModelStreamDeltaEvent
from imbue_core.agents.llm_apis.stream import LanguageModelStreamEndEvent
from imbue_core.agents.llm_apis.stream import LanguageModelStreamEvent
from imbue_core.agents.llm_apis.stream import LanguageModelStreamStartEvent
from imbue_core.frozen_utils import FrozenDict
from imbue_core.frozen_utils import FrozenMapping
from imbue_core.itertools import only
from imbue_core.secrets_utils import get_secret


# This function is monkeypatched as the original method does not catch BaseExceptions and asyncio.CancelledErrors are BaseExceptions
async def arequest(
    self: APIRequestor,
    options: TogetherRequest,
    stream: bool = False,
    request_timeout: float | tuple[float, float] | None = None,
) -> tuple[TogetherResponse | AsyncGenerator[TogetherResponse, None], bool, str | None]:
    ctx = AioHTTPSession()
    session = await ctx.__aenter__()
    result = None
    try:
        result = await self.arequest_raw(
            options,
            session,
            request_timeout=request_timeout,
        )
        resp, got_stream = await self._interpret_async_response(result, stream)
    except BaseException:
        # Close the request before exiting session context.
        if result is not None:
            result.release()
        await ctx.__aexit__(None, None, None)
        raise
    if got_stream:

        async def wrap_resp() -> AsyncGenerator[TogetherResponse, None]:
            assert isinstance(resp, AsyncGenerator)
            try:
                async for r in resp:
                    yield r
            finally:
                # Close the request before exiting session context. Important to do it here
                # as if stream is not fully exhausted, we need to close the request nevertheless.
                result.release()
                await ctx.__aexit__(None, None, None)

        return wrap_resp(), got_stream, self.api_key
    else:
        # Close the request before exiting session context.
        result.release()
        await ctx.__aexit__(None, None, None)
        return resp, got_stream, self.api_key


APIRequestor.arequest = arequest  # pyre-fixme[8]: pyre is confused about this


class TogetherAIModelName(enum.StrEnum):
    GOOGLE_GEMMA_2_27B_IT = "together/google/gemma-2-27b-it"
    GOOGLE_GEMMA_2_9B_IT = "together/google/gemma-2-9b-it"
    GOOGLE_GEMMA_2B_IT = "together/google/gemma-2b-it"
    META_LLAMA_3_2_3B_INSTRUCT_TURBO = "together/meta-llama/Llama-3.2-3B-Instruct-Turbo"
    META_LLAMA_3_3_70B_INSTRUCT_TURBO = "together/meta-llama/Llama-3.3-70B-Instruct-Turbo"
    META_LLAMA_3_70B_CHAT_HF = "together/meta-llama/Llama-3-70b-chat-hf"
    META_LLAMA_3_8B_CHAT_HF = "together/meta-llama/Llama-3-8b-chat-hf"
    META_LLAMA_3_1_405B_INSTRUCT_TURBO = "together/meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo"
    META_LLAMA_3_1_70B_INSTRUCT_TURBO = "together/meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo"
    META_LLAMA_3_1_8B_INSTRUCT_TURBO = "together/meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo"
    META_LLAMA_3_70B_INSTRUCT_LITE = "together/meta-llama/Meta-Llama-3-70B-Instruct-Lite"
    META_LLAMA_3_70B_INSTRUCT_TURBO = "together/meta-llama/Meta-Llama-3-70B-Instruct-Turbo"
    META_LLAMA_3_8B_INSTRUCT_LITE = "together/meta-llama/Meta-Llama-3-8B-Instruct-Lite"
    META_LLAMA_3_8B_INSTRUCT_TURBO = "together/meta-llama/Meta-Llama-3-8B-Instruct-Turbo"
    MISTRALAI_MISTRAL_7B_INSTRUCT_V0_1 = "together/mistralai/Mistral-7B-Instruct-v0.1"
    MISTRALAI_MISTRAL_7B_INSTRUCT_V0_2 = "together/mistralai/Mistral-7B-Instruct-v0.2"
    MISTRALAI_MISTRAL_7B_INSTRUCT_V0_3 = "together/mistralai/Mistral-7B-Instruct-v0.3"
    MISTRALAI_MIXTRAL_8X22B_INSTRUCT_V0_1 = "together/mistralai/Mixtral-8x22B-Instruct-v0.1"
    MISTRALAI_MIXTRAL_8X7B_INSTRUCT_V0_1 = "together/mistralai/Mixtral-8x7B-Instruct-v0.1"
    NOUSRESEARCH_NOUS_HERMES_2_MIXTRAL_8X7B_DPO = "together/NousResearch/Nous-Hermes-2-Mixtral-8x7B-DPO"
    DEEPSEEK_R1 = "together/deepseek-ai/DeepSeek-R1"
    OPENAI_GPT_OSS_20B = "together/openai/gpt-oss-20b"
    OPENAI_GPT_OSS_120B = "together/openai/gpt-oss-120b"
    # TOGETHERCOMPUTER_LLAMA_3_8B_CHAT_HF_INT4 = "together/togethercomputer/Llama-3-8b-chat-hf-int4"
    # TOGETHERCOMPUTER_LLAMA_3_8B_CHAT_HF_INT8 = "together/togethercomputer/Llama-3-8b-chat-hf-int8"


# Rate limits for Together AI models based on published API documentation
# Reference: https://docs.together.ai/docs/rate-limits
# Using Tier 5 rate limits (6,000 RPM)

TOGETHERAI_MODEL_INFO_BY_NAME: FrozenMapping[TogetherAIModelName, ModelInfo] = FrozenDict(
    {
        # ref https://docs.together.ai/docs/chat-models
        # pricing ref https://www.together.ai/pricing
        TogetherAIModelName.GOOGLE_GEMMA_2_27B_IT: ModelInfo(
            model_name=str(TogetherAIModelName.GOOGLE_GEMMA_2_27B_IT),
            cost_per_input_token=0.8 / 1_000_000,
            cost_per_output_token=0.8 / 1_000_000,
            max_input_tokens=8192,
            max_output_tokens=None,
            rate_limit_req=6000 / 60,  # 6000 RPM = 100.00 RPS
        ),
        TogetherAIModelName.GOOGLE_GEMMA_2_9B_IT: ModelInfo(
            model_name=str(TogetherAIModelName.GOOGLE_GEMMA_2_9B_IT),
            cost_per_input_token=0.3 / 1_000_000,
            cost_per_output_token=0.3 / 1_000_000,
            max_input_tokens=8192,
            max_output_tokens=None,
            rate_limit_req=6000 / 60,  # 6000 RPM = 100.00 RPS
        ),
        TogetherAIModelName.GOOGLE_GEMMA_2B_IT: ModelInfo(
            model_name=str(TogetherAIModelName.GOOGLE_GEMMA_2B_IT),
            cost_per_input_token=0.1 / 1_000_000,
            cost_per_output_token=0.1 / 1_000_000,
            max_input_tokens=8192,
            max_output_tokens=None,
            rate_limit_req=6000 / 60,  # 6000 RPM = 100.00 RPS
        ),
        TogetherAIModelName.META_LLAMA_3_2_3B_INSTRUCT_TURBO: ModelInfo(
            model_name=str(TogetherAIModelName.META_LLAMA_3_2_3B_INSTRUCT_TURBO),
            cost_per_input_token=0.06 / 1_000_000,
            cost_per_output_token=0.06 / 1_000_000,
            max_input_tokens=131072,
            max_output_tokens=None,
            rate_limit_req=6000 / 60,  # 6000 RPM = 100.00 RPS
        ),
        TogetherAIModelName.META_LLAMA_3_3_70B_INSTRUCT_TURBO: ModelInfo(
            model_name=str(TogetherAIModelName.META_LLAMA_3_3_70B_INSTRUCT_TURBO),
            cost_per_input_token=0.88 / 1_000_000,
            cost_per_output_token=0.88 / 1_000_000,
            max_input_tokens=131072,
            max_output_tokens=None,
            rate_limit_req=6000 / 60,  # 6000 RPM = 100.00 RPS
        ),
        TogetherAIModelName.META_LLAMA_3_70B_CHAT_HF: ModelInfo(
            model_name=str(TogetherAIModelName.META_LLAMA_3_70B_CHAT_HF),
            cost_per_input_token=0.88 / 1_000_000,
            cost_per_output_token=0.88 / 1_000_000,
            max_input_tokens=8192,
            max_output_tokens=None,
            rate_limit_req=6000 / 60,  # 6000 RPM = 100.00 RPS
        ),
        TogetherAIModelName.META_LLAMA_3_8B_CHAT_HF: ModelInfo(
            model_name=str(TogetherAIModelName.META_LLAMA_3_8B_CHAT_HF),
            cost_per_input_token=0.2 / 1_000_000,
            cost_per_output_token=0.2 / 1_000_000,
            max_input_tokens=8192,
            max_output_tokens=None,
            rate_limit_req=6000 / 60,  # 6000 RPM = 100.00 RPS
        ),
        TogetherAIModelName.META_LLAMA_3_1_405B_INSTRUCT_TURBO: ModelInfo(
            model_name=str(TogetherAIModelName.META_LLAMA_3_1_405B_INSTRUCT_TURBO),
            cost_per_input_token=3.5 / 1_000_000,
            cost_per_output_token=3.5 / 1_000_000,
            max_input_tokens=130815,
            max_output_tokens=None,
            rate_limit_req=6000 / 60,  # 6000 RPM = 100.00 RPS
        ),
        TogetherAIModelName.META_LLAMA_3_1_70B_INSTRUCT_TURBO: ModelInfo(
            model_name=str(TogetherAIModelName.META_LLAMA_3_1_70B_INSTRUCT_TURBO),
            cost_per_input_token=0.88 / 1_000_000,
            cost_per_output_token=0.88 / 1_000_000,
            max_input_tokens=131072,
            max_output_tokens=None,
            rate_limit_req=6000 / 60,  # 6000 RPM = 100.00 RPS
        ),
        TogetherAIModelName.META_LLAMA_3_1_8B_INSTRUCT_TURBO: ModelInfo(
            model_name=str(TogetherAIModelName.META_LLAMA_3_1_8B_INSTRUCT_TURBO),
            cost_per_input_token=0.18 / 1_000_000,
            cost_per_output_token=0.18 / 1_000_000,
            max_input_tokens=131072,
            max_output_tokens=None,
            rate_limit_req=6000 / 60,  # 6000 RPM = 100.00 RPS
        ),
        TogetherAIModelName.META_LLAMA_3_70B_INSTRUCT_LITE: ModelInfo(
            model_name=str(TogetherAIModelName.META_LLAMA_3_70B_INSTRUCT_LITE),
            cost_per_input_token=0.54 / 1_000_000,
            cost_per_output_token=0.54 / 1_000_000,
            max_input_tokens=8192,
            max_output_tokens=None,
            rate_limit_req=6000 / 60,  # 6000 RPM = 100.00 RPS
        ),
        TogetherAIModelName.META_LLAMA_3_70B_INSTRUCT_TURBO: ModelInfo(
            model_name=str(TogetherAIModelName.META_LLAMA_3_70B_INSTRUCT_TURBO),
            cost_per_input_token=0.88 / 1_000_000,
            cost_per_output_token=0.88 / 1_000_000,
            max_input_tokens=8192,
            max_output_tokens=None,
            rate_limit_req=6000 / 60,  # 6000 RPM = 100.00 RPS
        ),
        TogetherAIModelName.META_LLAMA_3_8B_INSTRUCT_LITE: ModelInfo(
            model_name=str(TogetherAIModelName.META_LLAMA_3_8B_INSTRUCT_LITE),
            cost_per_input_token=0.1 / 1_000_000,
            cost_per_output_token=0.1 / 1_000_000,
            max_input_tokens=8192,
            max_output_tokens=None,
            rate_limit_req=6000 / 60,  # 6000 RPM = 100.00 RPS
        ),
        TogetherAIModelName.META_LLAMA_3_8B_INSTRUCT_TURBO: ModelInfo(
            model_name=str(TogetherAIModelName.META_LLAMA_3_8B_INSTRUCT_TURBO),
            cost_per_input_token=0.18 / 1_000_000,
            cost_per_output_token=0.18 / 1_000_000,
            max_input_tokens=8192,
            max_output_tokens=None,
            rate_limit_req=6000 / 60,  # 6000 RPM = 100.00 RPS
        ),
        TogetherAIModelName.MISTRALAI_MISTRAL_7B_INSTRUCT_V0_1: ModelInfo(
            model_name=str(TogetherAIModelName.MISTRALAI_MISTRAL_7B_INSTRUCT_V0_1),
            cost_per_input_token=0.2 / 1_000_000,
            cost_per_output_token=0.2 / 1_000_000,
            max_input_tokens=32768,
            max_output_tokens=None,
            rate_limit_req=6000 / 60,  # 6000 RPM = 100.00 RPS
        ),
        TogetherAIModelName.MISTRALAI_MISTRAL_7B_INSTRUCT_V0_2: ModelInfo(
            model_name=str(TogetherAIModelName.MISTRALAI_MISTRAL_7B_INSTRUCT_V0_2),
            cost_per_input_token=0.2 / 1_000_000,
            cost_per_output_token=0.2 / 1_000_000,
            max_input_tokens=32768,
            max_output_tokens=None,
            rate_limit_req=6000 / 60,  # 6000 RPM = 100.00 RPS
        ),
        TogetherAIModelName.MISTRALAI_MISTRAL_7B_INSTRUCT_V0_3: ModelInfo(
            model_name=str(TogetherAIModelName.MISTRALAI_MISTRAL_7B_INSTRUCT_V0_3),
            cost_per_input_token=0.2 / 1_000_000,
            cost_per_output_token=0.2 / 1_000_000,
            max_input_tokens=32768,
            max_output_tokens=None,
            rate_limit_req=6000 / 60,  # 6000 RPM = 100.00 RPS
        ),
        TogetherAIModelName.MISTRALAI_MIXTRAL_8X22B_INSTRUCT_V0_1: ModelInfo(
            model_name=str(TogetherAIModelName.MISTRALAI_MIXTRAL_8X22B_INSTRUCT_V0_1),
            cost_per_input_token=1.2 / 1_000_000,
            cost_per_output_token=1.2 / 1_000_000,
            max_input_tokens=65536,
            max_output_tokens=None,
            rate_limit_req=6000 / 60,  # 6000 RPM = 100.00 RPS
        ),
        TogetherAIModelName.MISTRALAI_MIXTRAL_8X7B_INSTRUCT_V0_1: ModelInfo(
            model_name=str(TogetherAIModelName.MISTRALAI_MIXTRAL_8X7B_INSTRUCT_V0_1),
            cost_per_input_token=0.6 / 1_000_000,
            cost_per_output_token=0.6 / 1_000_000,
            max_input_tokens=32768,
            max_output_tokens=None,
            rate_limit_req=6000 / 60,  # 6000 RPM = 100.00 RPS
        ),
        TogetherAIModelName.NOUSRESEARCH_NOUS_HERMES_2_MIXTRAL_8X7B_DPO: ModelInfo(
            model_name=str(TogetherAIModelName.NOUSRESEARCH_NOUS_HERMES_2_MIXTRAL_8X7B_DPO),
            cost_per_input_token=0.6 / 1_000_000,
            cost_per_output_token=0.6 / 1_000_000,
            max_input_tokens=32768,
            max_output_tokens=None,
            rate_limit_req=6000 / 60,  # 6000 RPM = 100.00 RPS
        ),
        TogetherAIModelName.DEEPSEEK_R1: ModelInfo(
            model_name=str(TogetherAIModelName.DEEPSEEK_R1),
            cost_per_input_token=3.0 / 1_000_000,
            cost_per_output_token=7.0 / 1_000_000,
            max_input_tokens=32768,
            max_output_tokens=None,
            rate_limit_req=6000 / 60,  # 6000 RPM = 100.00 RPS
        ),
        TogetherAIModelName.OPENAI_GPT_OSS_20B: ModelInfo(
            model_name=str(TogetherAIModelName.OPENAI_GPT_OSS_20B),
            cost_per_input_token=0.00 / 1_000_000,
            cost_per_output_token=0.00 / 1_000_000,
            max_input_tokens=131_072,
            max_output_tokens=131_072,
            rate_limit_req=6000 / 60,  # 6000 RPM = 100.00 RPS
        ),
        TogetherAIModelName.OPENAI_GPT_OSS_120B: ModelInfo(
            model_name=str(TogetherAIModelName.OPENAI_GPT_OSS_120B),
            cost_per_input_token=0.00 / 1_000_000,
            cost_per_output_token=0.00 / 1_000_000,
            max_input_tokens=131_072,
            max_output_tokens=131_072,
            rate_limit_req=6000 / 60,  # 6000 RPM = 100.00 RPS
        ),
    }
)


def _default_capacity_semaphor() -> asyncio.Semaphore:
    return asyncio.Semaphore(100)


_CAPACITY_SEMAPHOR_BY_MODEL_NAME: Mapping[str, asyncio.Semaphore] = defaultdict(_default_capacity_semaphor)


_ROLE_TO_TOGETHERAI_ROLE: Final[FrozenMapping] = FrozenDict(
    {
        "HUMAN": "user",
        "ASSISTANT": "assistant",
        "SYSTEM": "system",
        "SYSTEM_CACHED": "system",
        "USER": "user",
        "USER_CACHED": "user",
    }
)

# ref: https://github.com/togethercomputer/together-python/blob/main/src/together/types/common.py#L13
_TOGETHERAI_STOP_REASON_TO_STOP_REASON: Final[FrozenMapping[str, ResponseStopReason]] = FrozenDict(
    {
        "length": ResponseStopReason.MAX_TOKENS,
        # This is a little sketchy, we treat them the same since we don't know which models emit stop sequence reasons
        # Since we don't want to break downstream applications that may require ending in the stop sequence
        # This is similar to how openai models are treated
        "stop": ResponseStopReason.END_TURN,
        "eos": ResponseStopReason.END_TURN,
        "tool_calls": ResponseStopReason.TOOL_CALLS,
        "error": ResponseStopReason.ERROR,
        "None": ResponseStopReason.NONE,
    }
)


def convert_prompt_to_together_messages(prompt: str) -> list[dict[str, str]]:
    prompt = prompt.lstrip()
    assert prompt.endswith("\n[ROLE=ASSISTANT]\n"), "prompt must end with [ROLE=ASSISTANT], prompt=\n" + prompt
    prompt = "".join(prompt.rsplit("\n[ROLE=ASSISTANT]\n", 1))
    assert prompt.startswith("[ROLE=")
    prompt = prompt.replace("[ROLE=", "", 1)
    chunks = prompt.split("\n[ROLE=")
    messages: list[dict[str, str]] = []
    for chunk in chunks:
        lines = chunk.split("\n")
        role = lines[0].strip().rstrip("]")
        assert role in (
            "HUMAN",
            "ASSISTANT",
            "USER",
            "SYSTEM",
            "SYSTEM_CACHED",
            "USER_CACHED",
        ), f"Unknown role {role} in prompt {prompt}"
        lines.pop(0)
        if len(messages) > 0:
            messages[-1]["content"] = messages[-1]["content"] + "\n"
        messages.append({"role": _ROLE_TO_TOGETHERAI_ROLE[role], "content": "\n".join(lines)})
    return messages


@contextmanager
def _together_exception_manager() -> Iterator[None]:
    """Simple context manager for parsing TogetherAI API exceptions."""
    # ref https://github.com/togethercomputer/together-python/blob/main/src/together/abstract/api_requestor.py#L332
    try:
        yield
    except RateLimitError as e:
        logger.info("Rate limited? {}", e)
        raise TransientLanguageModelError("RateLimitError") from e
    except InvalidRequestError as e:
        logger.info("BadAPIRequestError {}", e)
        raise BadAPIRequestError(str(e)) from e
    except AuthenticationError as e:
        logger.info("API Authentication error {}", e)
        raise
    except APIError as e:
        logger.info("Received APIError {}", e)
        raise
    except ServiceUnavailableError as e:
        logger.info("Received ServiceUnavailableError {}", e)
        raise TransientLanguageModelError("ServiceUnavailableError") from e
    except APIConnectionError as e:
        logger.info("Received APIConnectionError {}", e)
        raise TransientLanguageModelError("APIConnectionError") from e
    # Note, the together python SDK uses aiohttp under the hood
    # but takes care of parsing the main aiohttp exceptions into together API exceptions
    # ref https://github.com/togethercomputer/together-python/blob/main/src/together/abstract/api_requestor.py#L554


class TogetherAPI(LanguageModelAPI):
    model_name: TogetherAIModelName = TogetherAIModelName.META_LLAMA_3_1_8B_INSTRUCT_TURBO
    is_conversational: bool = True
    presence_penalty: float = 0.0
    # this shouldn't really ever even be used, but just in case
    stop_token_log_probability: float = math.log(0.9999)

    @field_validator("model_name")  # pyre-ignore[56]: pyre doesn't understand pydantic
    @classmethod
    def validate_model_name(cls, v: str) -> str:
        if v not in TOGETHERAI_MODEL_INFO_BY_NAME:
            raise LanguageModelInvalidModelNameError(v, cls.__name__, list(TOGETHERAI_MODEL_INFO_BY_NAME))
        return v

    @property
    def model_info(self) -> ModelInfo:
        return TOGETHERAI_MODEL_INFO_BY_NAME[self.model_name]

    @property
    def external_model_name(self) -> str:
        return self.model_name.replace("together/", "")

    def _get_client(self) -> AsyncTogether:
        api_key = get_secret("TOGETHER_API_KEY")
        if not api_key:
            raise MissingAPIKeyError("TOGETHER_API_KEY environment variable is not set")
        return AsyncTogether(api_key=api_key)

    async def _call_api(
        self,
        prompt: str,
        params: LanguageModelGenerationParams,
        network_failure_count: int = 0,
    ) -> CostedLanguageModelResponse:
        if params.max_tokens is None:
            logger.debug(
                "Togetherai API breaks if `max_tokens` not specified. Defaulting to `max_tokens=512`, make sure to specify this if you want something different."
            )
            params.max_tokens = 512

        with _together_exception_manager():
            messages = convert_prompt_to_together_messages(prompt)
            client = self._get_client()
            async with _CAPACITY_SEMAPHOR_BY_MODEL_NAME[self.model_name]:
                # ref: https://github.com/togethercomputer/together-python/blob/main/src/together/resources/chat/completions.py#L153
                api_result = await client.chat.completions.create(
                    model=self.external_model_name,
                    messages=messages,
                    max_tokens=params.max_tokens,
                    stop=[params.stop] if params.stop else None,
                    temperature=params.temperature,
                    top_k=5,
                    presence_penalty=self.presence_penalty,
                    stream=False,
                    logprobs=True,
                    n=params.count,
                    # currently don't specify this since tokenizer may change between models
                    logit_bias=None,
                )
                assert isinstance(api_result, ChatCompletionResponse)

        results = []
        choices = api_result.choices
        assert choices is not None
        for data in choices:
            message = data.message
            assert message is not None
            text = message.content
            assert text is not None
            assert isinstance(text, str)  # TODO: this is suspicious

            # TogetherAI only provides the logprob for the selected token
            logprobs = data.logprobs
            assert logprobs is not None
            tokens = logprobs.tokens
            token_logprobs = logprobs.token_logprobs
            assert tokens is not None and token_logprobs is not None
            assert all(token is not None for token in tokens)
            assert all(logprob is not None for logprob in token_logprobs)
            tokens = cast(Iterable[str], tokens)
            token_logprobs = cast(Iterable[float], token_logprobs)
            token_probabilities = [
                (TokenProbability(token=token, log_probability=logprob, is_stop=False),)
                for token, logprob in zip(tokens, token_logprobs)
            ]

            if data.finish_reason:
                stop_reason = _TOGETHERAI_STOP_REASON_TO_STOP_REASON[data.finish_reason.value]
            else:
                stop_reason = ResponseStopReason.NONE
            stop = params.stop
            if stop is not None and stop_reason == ResponseStopReason.END_TURN:
                text += stop
                token_probabilities.append(
                    (
                        TokenProbability(
                            token=stop,
                            log_probability=self.stop_token_log_probability,
                            is_stop=True,
                        ),
                    )
                )
            result = LanguageModelResponseWithLogits(
                text=text,
                token_probabilities=tuple(token_probabilities),
                token_count=len(token_probabilities),
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
        if params.max_tokens is None:
            logger.debug(
                "Togetherai API breaks if `max_tokens` not specified. Defaulting to `max_tokens=512`, make sure to specify this if you want something different."
            )
            params.max_tokens = 512

        with _together_exception_manager():
            messages = convert_prompt_to_together_messages(prompt)
            client = self._get_client()
            async with _CAPACITY_SEMAPHOR_BY_MODEL_NAME[self.model_name]:
                # ref: https://github.com/togethercomputer/together-python/blob/main/src/together/resources/chat/completions.py#L153
                api_result = await client.chat.completions.create(
                    model=self.external_model_name,
                    messages=messages,
                    max_tokens=params.max_tokens,
                    stop=[params.stop] if params.stop else None,
                    temperature=params.temperature,
                    top_k=5,
                    presence_penalty=self.presence_penalty,
                    stream=True,
                    # currently we don't support logprobs with streaming
                    logprobs=False,
                    n=1,
                    # currently don't specify this since tokenizer may change between models
                    logit_bias=None,
                )
                assert isinstance(api_result, AsyncGenerator)

            yield LanguageModelStreamStartEvent()

            usage = None
            finish_reason: str | None = None
            async for chunk in api_result:
                if chunk.usage:
                    usage = chunk.usage

                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason.value

                chunk_choices = chunk.choices
                if chunk_choices:
                    assert len(chunk_choices) == 1, "Currently only count=1 supported for streaming API."
                    delta = only(chunk_choices).delta
                    if delta and delta.content:
                        yield LanguageModelStreamDeltaEvent(delta=delta.content)

            stop_reason = _TOGETHERAI_STOP_REASON_TO_STOP_REASON[str(finish_reason)]

            if params.stop is not None and stop_reason == ResponseStopReason.END_TURN:
                yield LanguageModelStreamDeltaEvent(delta=params.stop)

            if usage is not None:
                completion_tokens = usage.completion_tokens
                prompt_tokens = usage.prompt_tokens
            else:
                completion_tokens = 0
                prompt_tokens = 0
            dollars_used = self.calculate_cost(prompt_tokens, completion_tokens)
            logger.trace("dollars used: {}", dollars_used)

            yield LanguageModelStreamEndEvent(
                usage=LanguageModelResponseUsage(
                    prompt_tokens_used=prompt_tokens,
                    completion_tokens_used=completion_tokens,
                    dollars_used=dollars_used,
                ),
                stop_reason=stop_reason,
            )
