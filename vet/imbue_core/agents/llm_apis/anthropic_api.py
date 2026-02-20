import enum
import inspect
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from types import FrameType
from typing import AsyncGenerator
from typing import Final
from typing import Iterator

import anthropic
import httpx
import tiktoken
from anthropic._types import NOT_GIVEN
from anthropic.types import CacheControlEphemeralParam
from anthropic.types import MessageParam
from anthropic.types import TextBlockParam
from loguru import logger
from pydantic.functional_validators import field_validator

from vet.imbue_core.agents.llm_apis.anthropic_data_types import AnthropicCachingInfo
from vet.imbue_core.agents.llm_apis.anthropic_data_types import AnthropicModelInfo
from vet.imbue_core.agents.llm_apis.api_utils import convert_prompt_to_messages
from vet.imbue_core.agents.llm_apis.api_utils import create_costed_language_model_response_for_single_result
from vet.imbue_core.agents.llm_apis.data_types import CachedCountTokensResponse
from vet.imbue_core.agents.llm_apis.data_types import CachingInfo
from vet.imbue_core.agents.llm_apis.data_types import CostedLanguageModelResponse
from vet.imbue_core.agents.llm_apis.data_types import CountTokensInputs
from vet.imbue_core.agents.llm_apis.data_types import CountTokensResponse
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelGenerationParams
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelResponseUsage
from vet.imbue_core.agents.llm_apis.data_types import ResponseStopReason
from vet.imbue_core.agents.llm_apis.errors import BadAPIRequestError
from vet.imbue_core.agents.llm_apis.errors import LanguageModelInvalidModelNameError
from vet.imbue_core.agents.llm_apis.errors import MissingAPIKeyError
from vet.imbue_core.agents.llm_apis.errors import NewSeedRetriableLanguageModelError
from vet.imbue_core.agents.llm_apis.errors import SafelyRetriableTransientLanguageModelError
from vet.imbue_core.agents.llm_apis.errors import TransientLanguageModelError
from vet.imbue_core.agents.llm_apis.errors import UnsetCachePathError
from vet.imbue_core.agents.llm_apis.language_model_api import LanguageModelAPI
from vet.imbue_core.agents.llm_apis.models import ModelInfo
from vet.imbue_core.agents.llm_apis.stream import LanguageModelStreamDeltaEvent
from vet.imbue_core.agents.llm_apis.stream import LanguageModelStreamEndEvent
from vet.imbue_core.agents.llm_apis.stream import LanguageModelStreamEvent
from vet.imbue_core.agents.llm_apis.stream import LanguageModelStreamStartEvent
from vet.imbue_core.async_monkey_patches import log_exception
from vet.imbue_core.caching import AsyncCache
from vet.imbue_core.frozen_utils import FrozenDict
from vet.imbue_core.frozen_utils import FrozenMapping
from vet.imbue_core.itertools import only
from vet.imbue_core.nested_evolver import assign
from vet.imbue_core.nested_evolver import chill
from vet.imbue_core.nested_evolver import evolver
from vet.imbue_core.secrets_utils import get_secret


class AnthropicModelName(enum.StrEnum):
    CLAUDE_3_HAIKU_2024_03_07 = "claude-3-haiku-20240307"
    CLAUDE_3_OPUS_2024_02_29 = "claude-3-opus-20240229"
    CLAUDE_3_5_SONNET_2024_06_20 = "claude-3-5-sonnet-20240620"
    CLAUDE_3_5_SONNET_2024_10_22 = "claude-3-5-sonnet-20241022"
    CLAUDE_3_5_HAIKU_2024_10_22 = "claude-3-5-haiku-20241022"
    CLAUDE_3_7_SONNET_2025_02_19 = "claude-3-7-sonnet-20250219"
    CLAUDE_4_OPUS_2025_05_14 = "claude-opus-4-20250514"
    CLAUDE_4_1_OPUS_2025_08_05 = "claude-opus-4-1-20250805"
    CLAUDE_4_SONNET_2025_05_14 = "claude-sonnet-4-20250514"
    CLAUDE_4_5_SONNET_2025_09_29 = "claude-sonnet-4-5-20250929"
    CLAUDE_4_5_HAIKU_2025_10_01 = "claude-haiku-4-5-20251001"
    CLAUDE_4_5_OPUS_2025_11_01 = "claude-opus-4-5-20251101"
    CLAUDE_4_6_OPUS = "claude-opus-4-6"
    # the same as above but with the token limit and cost per token for the 1M token limit
    # TODO: combine these and add ability for token costs to be nonlinear
    # FIXME: this is an exception where the model name is not the same as the model name in the API
    CLAUDE_4_SONNET_2025_05_14_LONG = "claude-sonnet-4-20250514-long"
    CLAUDE_4_5_SONNET_2025_09_29_LONG = "claude-sonnet-4-5-20250929-long"
    CLAUDE_4_6_OPUS_LONG = "claude-opus-4-6-long"

    # the following are 'retired' and are no longer available: https://docs.claude.com/en/docs/about-claude/model-deprecations
    # CLAUDE_2_1 = "claude-2.1"
    # CLAUDE_2 = "claude-2"
    # CLAUDE_3_SONNET_2024_02_29 = "claude-3-sonnet-20240229"


# Basic info is available at https://docs.anthropic.com/claude/reference/models
# Rate limits for Anthropic models are available on our dashboard: https://console.anthropic.com/settings/limits
# (we have a custom plan, so the public docs don't reflect our actual rate limits)
# Prompt caching pricing is available at https://docs.claude.com/en/docs/build-with-claude/prompt-caching#pricing
# NOTE: as of 2025-06-04, there are some models that don't have rate limits set in our dashboard
ANTHROPIC_MODEL_INFO_BY_NAME: FrozenMapping[AnthropicModelName, ModelInfo] = FrozenDict(
    {
        AnthropicModelName.CLAUDE_3_HAIKU_2024_03_07: ModelInfo(
            model_name=AnthropicModelName.CLAUDE_3_HAIKU_2024_03_07,
            cost_per_input_token=0.25 / 1_000_000,
            cost_per_output_token=1.25 / 1_000_000,
            max_input_tokens=200_000,
            max_output_tokens=4096,
            rate_limit_req=4000 / 60,  # 4000 RPM = 66.67 RPS
            rate_limit_tok=4_000_000 / 60,
            rate_limit_output_tok=800_000 / 60,
            provider_specific_info=AnthropicModelInfo(
                cost_per_5m_cache_write_token=0.3 / 1_000_000,
                cost_per_1h_cache_write_token=0.5 / 1_000_000,
                cost_per_cache_read_token=0.03 / 1_000_000,
            ),
        ),
        AnthropicModelName.CLAUDE_3_OPUS_2024_02_29: ModelInfo(
            model_name=AnthropicModelName.CLAUDE_3_OPUS_2024_02_29,
            cost_per_input_token=15.00 / 1_000_000,
            cost_per_output_token=75.00 / 1_000_000,
            max_input_tokens=200_000,
            max_output_tokens=4096,
            rate_limit_req=4000 / 60,  # 4000 RPM = 66.67 RPS
            rate_limit_tok=1_000_000 / 60,
            rate_limit_output_tok=150_000 / 60,
            provider_specific_info=AnthropicModelInfo(
                cost_per_5m_cache_write_token=18.75 / 1_000_000,
                cost_per_1h_cache_write_token=30 / 1_000_000,
                cost_per_cache_read_token=1.5 / 1_000_000,
            ),
        ),
        AnthropicModelName.CLAUDE_3_5_SONNET_2024_06_20: ModelInfo(
            model_name=AnthropicModelName.CLAUDE_3_5_SONNET_2024_06_20,
            cost_per_input_token=3.00 / 1_000_000,
            cost_per_output_token=15.00 / 1_000_000,
            max_input_tokens=200_000,
            max_output_tokens=4096,
            rate_limit_req=5000 / 60,  # 5000 RPM = 83.33 RPS
            rate_limit_tok=8_000_000 / 60,
            rate_limit_output_tok=1_600_000 / 60,
            provider_specific_info=AnthropicModelInfo(
                cost_per_5m_cache_write_token=3.75 / 1_000_000,
                cost_per_1h_cache_write_token=6 / 1_000_000,
                cost_per_cache_read_token=0.3 / 1_000_000,
            ),
        ),
        AnthropicModelName.CLAUDE_3_5_SONNET_2024_10_22: ModelInfo(
            model_name=AnthropicModelName.CLAUDE_3_5_SONNET_2024_10_22,
            cost_per_input_token=3.00 / 1_000_000,
            cost_per_output_token=15.00 / 1_000_000,
            max_input_tokens=200_000,
            max_output_tokens=8192,
            rate_limit_req=5000 / 60,  # 5000 RPM = 83.33 RPS
            rate_limit_tok=8_000_000 / 60,
            rate_limit_output_tok=400_000 / 60,
        ),
        AnthropicModelName.CLAUDE_3_5_HAIKU_2024_10_22: ModelInfo(
            model_name=AnthropicModelName.CLAUDE_3_5_HAIKU_2024_10_22,
            cost_per_input_token=1.00 / 1_000_000,
            cost_per_output_token=5.00 / 1_000_000,
            max_input_tokens=200_000,
            max_output_tokens=8192,
            rate_limit_req=4000 / 60,  # 4000 RPM = 66.67 RPS
            rate_limit_tok=4_000_000 / 60,
            rate_limit_output_tok=800_000 / 60,
            provider_specific_info=AnthropicModelInfo(
                cost_per_5m_cache_write_token=1 / 1_000_000,
                cost_per_1h_cache_write_token=1.6 / 1_000_000,
                cost_per_cache_read_token=0.08 / 1_000_000,
            ),
        ),
        AnthropicModelName.CLAUDE_3_7_SONNET_2025_02_19: ModelInfo(
            model_name=AnthropicModelName.CLAUDE_3_7_SONNET_2025_02_19,
            cost_per_input_token=3.00 / 1_000_000,
            cost_per_output_token=15.00 / 1_000_000,
            max_input_tokens=200_000,
            max_output_tokens=8192,
            rate_limit_req=None,  # Currently no limit set in our dashboard
            rate_limit_tok=2_000_000 / 60,
            rate_limit_output_tok=400_000 / 60,
            provider_specific_info=AnthropicModelInfo(
                cost_per_5m_cache_write_token=3.75 / 1_000_000,
                cost_per_1h_cache_write_token=6 / 1_000_000,
                cost_per_cache_read_token=0.3 / 1_000_000,
            ),
        ),
        AnthropicModelName.CLAUDE_4_OPUS_2025_05_14: ModelInfo(
            model_name=AnthropicModelName.CLAUDE_4_OPUS_2025_05_14,
            cost_per_input_token=15.00 / 1_000_000,
            cost_per_output_token=75.00 / 1_000_000,
            max_input_tokens=200_000,
            max_output_tokens=32_000,
            rate_limit_req=4000 / 60,
            rate_limit_tok=2_000_000 / 60,
            rate_limit_output_tok=400_000 / 60,
            provider_specific_info=AnthropicModelInfo(
                cost_per_5m_cache_write_token=18.75 / 1_000_000,
                cost_per_1h_cache_write_token=30 / 1_000_000,
                cost_per_cache_read_token=1.5 / 1_000_000,
            ),
        ),
        AnthropicModelName.CLAUDE_4_1_OPUS_2025_08_05: ModelInfo(
            model_name=AnthropicModelName.CLAUDE_4_1_OPUS_2025_08_05,
            cost_per_input_token=15.00 / 1_000_000,
            cost_per_output_token=75.00 / 1_000_000,
            max_input_tokens=200_000,
            max_output_tokens=32_000,
            rate_limit_req=4000 / 60,
            rate_limit_tok=2_000_000 / 60,
            rate_limit_output_tok=400_000 / 60,
            provider_specific_info=AnthropicModelInfo(
                cost_per_5m_cache_write_token=18.75 / 1_000_000,
                cost_per_1h_cache_write_token=30 / 1_000_000,
                cost_per_cache_read_token=1.5 / 1_000_000,
            ),
        ),
        AnthropicModelName.CLAUDE_4_5_OPUS_2025_11_01: ModelInfo(
            model_name=AnthropicModelName.CLAUDE_4_5_OPUS_2025_11_01,
            cost_per_input_token=5.00 / 1_000_000,
            cost_per_output_token=25.00 / 1_000_000,
            max_input_tokens=200_000,
            max_output_tokens=64_000,
            rate_limit_req=4000 / 60,
            rate_limit_tok=2_000_000 / 60,
            rate_limit_output_tok=400_000 / 60,
            provider_specific_info=AnthropicModelInfo(
                cost_per_5m_cache_write_token=6.25 / 1_000_000,
                cost_per_1h_cache_write_token=10 / 1_000_000,
                cost_per_cache_read_token=0.5 / 1_000_000,
            ),
        ),
        AnthropicModelName.CLAUDE_4_6_OPUS: ModelInfo(
            model_name=AnthropicModelName.CLAUDE_4_6_OPUS,
            cost_per_input_token=5.00 / 1_000_000,
            cost_per_output_token=25.00 / 1_000_000,
            max_input_tokens=200_000,
            max_output_tokens=128_000,
            rate_limit_req=4000 / 60,
            rate_limit_tok=2_000_000 / 60,
            rate_limit_output_tok=400_000 / 60,
            provider_specific_info=AnthropicModelInfo(
                cost_per_5m_cache_write_token=6.25 / 1_000_000,
                cost_per_1h_cache_write_token=10 / 1_000_000,
                cost_per_cache_read_token=0.50 / 1_000_000,
            ),
        ),
        AnthropicModelName.CLAUDE_4_SONNET_2025_05_14: ModelInfo(
            model_name=AnthropicModelName.CLAUDE_4_SONNET_2025_05_14,
            cost_per_input_token=3.00 / 1_000_000,
            cost_per_output_token=15.00 / 1_000_000,
            max_input_tokens=200_000,
            max_output_tokens=64_000,
            rate_limit_req=None,  # Currently no limit set in our dashboard
            rate_limit_tok=2_000_000 / 60,
            rate_limit_output_tok=400_000 / 60,
            provider_specific_info=AnthropicModelInfo(
                cost_per_5m_cache_write_token=3.75 / 1_000_000,
                cost_per_1h_cache_write_token=6 / 1_000_000,
                cost_per_cache_read_token=0.3 / 1_000_000,
            ),
        ),
        AnthropicModelName.CLAUDE_4_5_SONNET_2025_09_29: ModelInfo(
            model_name=AnthropicModelName.CLAUDE_4_5_SONNET_2025_09_29,
            cost_per_input_token=3.00 / 1_000_000,
            cost_per_output_token=15.00 / 1_000_000,
            max_input_tokens=200_000,
            max_output_tokens=64_000,
            rate_limit_req=None,  # Currently no limit set in our dashboard
            rate_limit_tok=2_000_000 / 60,
            rate_limit_output_tok=400_000 / 60,
            provider_specific_info=AnthropicModelInfo(
                cost_per_5m_cache_write_token=3.75 / 1_000_000,
                cost_per_1h_cache_write_token=6 / 1_000_000,
                cost_per_cache_read_token=0.3 / 1_000_000,
            ),
        ),
        AnthropicModelName.CLAUDE_4_5_HAIKU_2025_10_01: ModelInfo(
            model_name=AnthropicModelName.CLAUDE_4_5_HAIKU_2025_10_01,
            cost_per_input_token=1.00 / 1_000_000,
            cost_per_output_token=5.00 / 1_000_000,
            max_input_tokens=200_000,
            max_output_tokens=64_000,
            rate_limit_req=4_000 / 60,
            rate_limit_tok=4_000_000 / 60,
            rate_limit_output_tok=800_000 / 60,
            provider_specific_info=AnthropicModelInfo(
                cost_per_5m_cache_write_token=1.25 / 1_000_000,
                cost_per_1h_cache_write_token=2.0 / 1_000_000,
                cost_per_cache_read_token=0.1 / 1_000_000,
            ),
        ),
        AnthropicModelName.CLAUDE_4_SONNET_2025_05_14_LONG: ModelInfo(
            model_name=AnthropicModelName.CLAUDE_4_SONNET_2025_05_14_LONG,
            # the first 200_000 input tokens use the rates above, and the next up to 800_000 use the rate 6.0 / 1_000_000.
            # thus the maximum average cost per input token is (3.0 * 200_000 + 6.0 * 800_000) / 1_000_000 = 5.4 per 1_000_000.
            # (all output tokens may be past 200_000 input tokens, so the max average cost there is just the cost for tokens after 200_000)
            cost_per_input_token=5.40 / 1_000_000,
            cost_per_output_token=22.50 / 1_000_000,
            max_input_tokens=1_000_000,
            max_output_tokens=64_000,
            rate_limit_req=None,  # Currently no limit set in our dashboard
            rate_limit_tok=1_000_000 / 60,  # <-- yeah they let us have one (1) 1M request per minute
            rate_limit_output_tok=200_000 / 60,
        ),
        AnthropicModelName.CLAUDE_4_5_SONNET_2025_09_29_LONG: ModelInfo(
            model_name=AnthropicModelName.CLAUDE_4_5_SONNET_2025_09_29_LONG,
            # the first 200_000 input tokens use the rates above, and the next up to 800_000 use the rate 6.0 / 1_000_000.
            # thus the maximum average cost per input token is (3.0 * 200_000 + 6.0 * 800_000) / 1_000_000 = 5.4 per 1_000_000.
            # (all output tokens may be past 200_000 input tokens, so the max average cost there is just the cost for tokens after 200_000)
            cost_per_input_token=5.40 / 1_000_000,
            cost_per_output_token=22.50 / 1_000_000,
            max_input_tokens=1_000_000,
            max_output_tokens=64_000,
            rate_limit_req=None,  # Currently no limit set in our dashboard
            rate_limit_tok=1_000_000 / 60,  # <-- yeah they let us have one (1) 1M request per minute
            rate_limit_output_tok=200_000 / 60,
        ),
        AnthropicModelName.CLAUDE_4_6_OPUS_LONG: ModelInfo(
            model_name=AnthropicModelName.CLAUDE_4_6_OPUS_LONG,
            # the first 200_000 input tokens use the rate 5.0 / 1_000_000, and the next up to 800_000 use the rate 10.0 / 1_000_000.
            # thus the maximum average cost per input token is (5.0 * 200_000 + 10.0 * 800_000) / 1_000_000 = 9.0 per 1_000_000.
            # (all output tokens may be past 200_000 input tokens, so the max average cost there is just the cost for tokens after 200_000)
            cost_per_input_token=9.00 / 1_000_000,
            cost_per_output_token=37.50 / 1_000_000,
            max_input_tokens=1_000_000,
            max_output_tokens=128_000,
            rate_limit_req=None,  # Currently no limit set in our dashboard
            rate_limit_tok=1_000_000 / 60,
            rate_limit_output_tok=200_000 / 60,
        ),
    }
)


_ROLE_TO_ANTHROPIC_ROLE: Final[FrozenMapping[str, str]] = FrozenDict(
    {
        "HUMAN": "user",
        "ASSISTANT": "assistant",
        "USER": "user",
        "USER_CACHED": "user",
        "SYSTEM": "system",
        "SYSTEM_CACHED": "system",
    }
)

_ANTHROPIC_STOP_REASON_TO_STOP_REASON: Final[FrozenMapping[str, ResponseStopReason]] = FrozenDict(
    {
        "end_turn": ResponseStopReason.END_TURN,
        "max_tokens": ResponseStopReason.MAX_TOKENS,
        "stop_sequence": ResponseStopReason.STOP_SEQUENCE,
        "refusal": ResponseStopReason.CONTENT_FILTER,
    }
)

_ANTHROPIC_BETA_PROMPT_CACHING = "prompt-caching-2024-07-31"
_ANTHROPIC_BETA_OAUTH = "oauth-2025-04-20"


@lru_cache(maxsize=1)
def get_anthropic_tokenizer() -> tiktoken.Encoding:
    """Use cl100k_base encoding as an approximation for Claude tokenization.

    Modern Anthropic SDK does not expose a tokenizer directly and instead
    relies on API calls to count tokens. Using that implementation would
    put HTTP calls in our `count_tokens` implementation which would be tricky
    as the method would have to be async or block the event loop.

    Instead, we use tiktoken's cl100k_base encoding (used by GPT-4) as a
    reasonable approximation. This allows us to count tokens without making
    HTTP requests at the cost of slightly inaccurate token counts.
    """
    return tiktoken.get_encoding("cl100k_base")


def count_anthropic_tokens(text: str) -> int:
    return int(len(get_anthropic_tokenizer().encode(text, disallowed_special=())) * 1.1)


SystemMessageParam = TextBlockParam


def _convert_prompt_to_anthropic_messages(
    prompt: str,
) -> tuple[list[MessageParam], list[SystemMessageParam] | None]:
    """Converts a prompt into list of non-system (user/assistant) messages and the optional system prompt."""
    non_system_messages = []
    system_messages = []
    for msg in convert_prompt_to_messages(prompt, is_cache_role_preserved=True):
        role = _ROLE_TO_ANTHROPIC_ROLE[msg.role]
        if msg.role == "SYSTEM_CACHED":
            system_messages.append(
                {
                    "type": "text",
                    "text": msg.content,
                    "cache_control": {"type": "ephemeral"},
                },
            )
        elif role == "system":
            system_messages.append(
                {
                    "type": "text",
                    "text": msg.content,
                },
            )
        elif role == "USER_CACHED":
            non_system_messages.append(
                MessageParam(  # pyre-fixme[28]: MessageParam doesn't have cache_control
                    content=msg.content,
                    role="user",
                    cache_control=CacheControlEphemeralParam(type="ephemeral"),
                )
            )
        else:
            non_system_messages.append(MessageParam(content=msg.content, role=role))  # type: ignore

    if len(system_messages) > 1:
        logger.debug("system_messages: {}", system_messages)
        raise ValueError(f"Anthropic API supports only 0 or 1 system message; got {len(system_messages)}.")

    if len(non_system_messages) == 0:
        system_messages = None

    return non_system_messages, system_messages


@contextmanager
def _anthropic_exception_manager() -> Iterator[None]:
    """Simple context manager for parsing Anthropic API exceptions."""
    # ref
    try:
        yield
    except anthropic.InternalServerError as e:
        # this can be caused by either malformed requests or transient errors, so play it safe and retry
        raise TransientLanguageModelError(str(e)) from e
    except anthropic.BadRequestError as e:
        logger.debug("BadAPIRequestError {e}", e=e)
        raise BadAPIRequestError(str(e)) from e
    except TypeError as e:
        logger.debug("Type error calling Anthropic API: {e}", e=e)
        raise BadAPIRequestError(str(e)) from e
    except anthropic.APIConnectionError as e:
        raise TransientLanguageModelError(str(e)) from e
    except anthropic.RateLimitError as e:
        extra_header_keys = [x for x in e.response.headers.keys() if x.startswith("anthropic-")]
        extra_data = ", ".join([f"{key}={e.response.headers[key]}" for key in extra_header_keys])
        extra_info = f"Rate limit data: {extra_data}"
        raise TransientLanguageModelError(extra_info) from e
    except anthropic.APIStatusError as e:
        if "overloaded_error" in str(e):
            raise SafelyRetriableTransientLanguageModelError(str(e)) from e
        if "internal server error" in str(e).lower():
            raise SafelyRetriableTransientLanguageModelError(str(e)) from e
        # this happens when anthropic provides us open source code and then feels bad about it
        # anthropic.APIStatusError: {'type': 'error', 'error': {'details': None, 'type': 'invalid_request_error', 'message': 'Output blocked by content filtering policy'}}
        if e.message == "Output blocked by content filtering policy":
            raise NewSeedRetriableLanguageModelError(e)
        logger.debug(str(e))
        if e.status_code == 409 or e.status_code >= 500:
            raise TransientLanguageModelError(str(e)) from e
        raise
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
            "Failed to generate output from Anthropic, unknown error of type {type_name}",
            type_name=type(e).__name__,
        )
        raise TransientLanguageModelError("Unknown error") from e


class MissingCachingInfoError(Exception):
    pass


class AnthropicAPI(LanguageModelAPI):
    model_name: AnthropicModelName = AnthropicModelName.CLAUDE_4_SONNET_2025_05_14
    is_conversational: bool = True

    # Anthropic specific args
    # unclear what the timeout ought to be actually, set to 1 minute for now because their default of 10 minutes seems insane
    timeout: float = 60.0
    max_retries: int = 0
    count_tokens_cache_path: Path | None = None

    @field_validator("model_name")  # pyre-ignore[56]: pyre doesn't understand pydantic
    @classmethod
    def validate_model_name(cls, v: str) -> str:
        if v not in ANTHROPIC_MODEL_INFO_BY_NAME:
            raise LanguageModelInvalidModelNameError(v, cls.__name__, list(ANTHROPIC_MODEL_INFO_BY_NAME))
        return v

    @property
    def model_info(self) -> ModelInfo:
        return ANTHROPIC_MODEL_INFO_BY_NAME[self.model_name]

    def _get_sync_client(self) -> anthropic.Anthropic:
        api_key, auth_token = _get_api_key_or_auth_token()
        if api_key:
            return anthropic.Anthropic(api_key=api_key)
        else:
            return anthropic.Anthropic(
                auth_token=auth_token,
                default_headers={"anthropic-beta": _ANTHROPIC_BETA_OAUTH},
            )

    def _get_client(self) -> anthropic.AsyncAnthropic:
        api_key, auth_token = _get_api_key_or_auth_token()
        if api_key:
            return anthropic.AsyncAnthropic(
                api_key=api_key,
                max_retries=self.max_retries,
                timeout=self.timeout,
                default_headers={"anthropic-beta": _ANTHROPIC_BETA_PROMPT_CACHING},
            )
        else:
            return anthropic.AsyncAnthropic(
                auth_token=auth_token,
                max_retries=self.max_retries,
                timeout=self.timeout,
                default_headers={"anthropic-beta": f"{_ANTHROPIC_BETA_PROMPT_CACHING},{_ANTHROPIC_BETA_OAUTH}"},
            )

    async def _call_api(
        self,
        prompt: str,
        params: LanguageModelGenerationParams,
        network_failure_count: int = 0,
    ) -> CostedLanguageModelResponse:
        assert (
            params.count == 1
        ), "Anthropic API only supports count=1.  It is possible to hack around this by using a for loop, but doesn't seem worth it right now."

        non_system_messages, system_messages = _convert_prompt_to_anthropic_messages(prompt)

        with _anthropic_exception_manager():
            async with self._get_client() as client:
                if params.max_tokens is None:
                    # NOTE: anthropic's API REQUIRES you to provide this, if you don't pass it in we just set it to the maximum possible

                    # use the evolver method of updating instead
                    # params.max_tokens = self.model_info.max_output_tokens
                    param_with_max_tokens_evolver = evolver(params)
                    assign(
                        param_with_max_tokens_evolver.max_tokens,
                        lambda: self.model_info.max_output_tokens,
                    )
                    params = chill(param_with_max_tokens_evolver)
                assert params.max_tokens is not None, "max_tokens must be provided for Anthropic API"

                if self.model_name in (
                    AnthropicModelName.CLAUDE_4_5_SONNET_2025_09_29_LONG,
                    AnthropicModelName.CLAUDE_4_SONNET_2025_05_14_LONG,
                    AnthropicModelName.CLAUDE_4_6_OPUS_LONG,
                ):
                    # FIXME: Fix this once this is no longer beta or as this becomes required for more models
                    # Map the name back to the actual model name for the API call
                    if self.model_name == AnthropicModelName.CLAUDE_4_5_SONNET_2025_09_29_LONG:
                        model_name = AnthropicModelName.CLAUDE_4_5_SONNET_2025_09_29
                    elif self.model_name == AnthropicModelName.CLAUDE_4_SONNET_2025_05_14_LONG:
                        model_name = AnthropicModelName.CLAUDE_4_SONNET_2025_05_14
                    elif self.model_name == AnthropicModelName.CLAUDE_4_6_OPUS_LONG:
                        model_name = AnthropicModelName.CLAUDE_4_6_OPUS
                    else:
                        assert False, "unreachable"
                    api_result = await client.beta.messages.create(
                        messages=non_system_messages,
                        stop_sequences=([params.stop] if params.stop is not None else NOT_GIVEN),
                        model=model_name,
                        temperature=params.temperature,
                        system=prepend_claude_code_system_prompt(system_messages),
                        max_tokens=params.max_tokens,
                        betas=["context-1m-2025-08-07"],
                    )
                    detailed_caching_data = AnthropicCachingInfo(
                        written_5m=api_result.usage.cache_creation.ephemeral_5m_input_tokens,
                        written_1h=api_result.usage.cache_creation.ephemeral_1h_input_tokens,
                    )
                else:
                    api_result = await client.messages.create(
                        messages=non_system_messages,
                        stop_sequences=([params.stop] if params.stop is not None else NOT_GIVEN),
                        model=self.model_name,
                        temperature=params.temperature,
                        system=prepend_claude_code_system_prompt(system_messages),
                        max_tokens=params.max_tokens,
                    )
                    detailed_caching_data = AnthropicCachingInfo(
                        written_5m=api_result.usage.cache_creation.ephemeral_5m_input_tokens,
                        written_1h=api_result.usage.cache_creation.ephemeral_1h_input_tokens,
                    )
                text = only(api_result.content).text
                if api_result.stop_reason:
                    stop_reason = _ANTHROPIC_STOP_REASON_TO_STOP_REASON.get(
                        str(api_result.stop_reason), ResponseStopReason.NONE
                    )
                else:
                    stop_reason = ResponseStopReason.NONE
                if params.stop and stop_reason == ResponseStopReason.STOP_SEQUENCE:
                    text += params.stop
                logger.trace(text)

                prompt_tokens = api_result.usage.input_tokens
                completion_tokens = api_result.usage.output_tokens  # type: ignore
                caching_info = CachingInfo(
                    read_from_cache=api_result.usage.cache_read_input_tokens,
                    provider_specific_data=detailed_caching_data,
                )
                dollars_used = self.calculate_cost(prompt_tokens, completion_tokens, caching_info)
                logger.trace("Dollars used: {dollars_used}", dollars_used=dollars_used)

                return create_costed_language_model_response_for_single_result(
                    text=text,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    stop_reason=stop_reason,
                    network_failure_count=network_failure_count,
                    dollars_used=dollars_used,
                    caching_info=caching_info,
                )

    async def _get_api_stream(
        self,
        prompt: str,
        params: LanguageModelGenerationParams,
    ) -> AsyncGenerator[LanguageModelStreamEvent, None]:
        non_system_messages, system_messages = _convert_prompt_to_anthropic_messages(prompt)
        with _anthropic_exception_manager():
            async with self._get_client() as client:
                yield LanguageModelStreamStartEvent()

                # NOTE: anthropic's API REQUIRES you to provide this, if you don't pass it in we just set it to the maximum possible
                max_tokens = params.max_tokens if params.max_tokens is not None else self.model_info.max_output_tokens
                assert max_tokens is not None, "max_tokens must be provided for Anthropic API"

                if self.model_name in (
                    AnthropicModelName.CLAUDE_4_5_SONNET_2025_09_29_LONG,
                    AnthropicModelName.CLAUDE_4_SONNET_2025_05_14_LONG,
                    AnthropicModelName.CLAUDE_4_6_OPUS_LONG,
                ):
                    # FIXME: Fix this once this is no longer beta or as this becomes required for more models
                    # Map the name back to the actual model name for the API call
                    if self.model_name == AnthropicModelName.CLAUDE_4_5_SONNET_2025_09_29_LONG:
                        model_name = AnthropicModelName.CLAUDE_4_5_SONNET_2025_09_29
                    elif self.model_name == AnthropicModelName.CLAUDE_4_SONNET_2025_05_14_LONG:
                        model_name = AnthropicModelName.CLAUDE_4_SONNET_2025_05_14
                    elif self.model_name == AnthropicModelName.CLAUDE_4_6_OPUS_LONG:
                        model_name = AnthropicModelName.CLAUDE_4_6_OPUS
                    else:
                        assert False, "unreachable"
                    stream_fn = lambda **kwargs: client.beta.messages.stream(**kwargs, betas=["context-1m-2025-08-07"])
                    cache_info_maker = lambda api_result: AnthropicCachingInfo(
                        written_5m=api_result.usage.cache_creation.ephemeral_5m_input_tokens,
                        written_1h=api_result.usage.cache_creation.ephemeral_1h_input_tokens,
                    )
                else:
                    model_name = self.model_name
                    stream_fn = lambda **kwargs: client.messages.stream(**kwargs)
                    cache_info_maker = lambda api_result: AnthropicCachingInfo(
                        written_5m=api_result.usage.cache_creation.ephemeral_5m_input_tokens,
                        written_1h=api_result.usage.cache_creation.ephemeral_1h_input_tokens,
                    )
                async with stream_fn(
                    max_tokens=max_tokens,
                    messages=non_system_messages,
                    model=model_name,
                    stop_sequences=([params.stop] if params.stop is not None else NOT_GIVEN),
                    system=system_messages or NOT_GIVEN,
                    temperature=params.temperature,
                ) as stream:
                    async for text_delta in stream.text_stream:
                        yield LanguageModelStreamDeltaEvent(delta=text_delta)

                    final_message = await stream.get_final_message()
                    text = only(final_message.content).text
                    stop_reason = (
                        final_message.stop_reason if final_message.stop_reason is not None else ResponseStopReason.NONE
                    )
                    if params.stop and stop_reason == ResponseStopReason.STOP_SEQUENCE:
                        yield LanguageModelStreamDeltaEvent(delta=params.stop)
                        text += params.stop
                    logger.trace(text)

                    prompt_tokens = final_message.usage.input_tokens
                    # useful to confirm that the cache is actually being hit
                    logger.debug(
                        "Used this many cached read tokens: {cached_tokens}",
                        cached_tokens=final_message.usage.cache_read_input_tokens,
                    )
                    completion_tokens = final_message.usage.output_tokens
                    caching_info = CachingInfo(
                        read_from_cache=final_message.usage.cache_read_input_tokens,
                        provider_specific_data=cache_info_maker(final_message),
                    )
                    dollars_used = self.calculate_cost(prompt_tokens, completion_tokens, caching_info)

                    if final_message.stop_reason:
                        stop_reason = _ANTHROPIC_STOP_REASON_TO_STOP_REASON.get(
                            str(final_message.stop_reason), ResponseStopReason.NONE
                        )
                    else:
                        stop_reason = ResponseStopReason.NONE

                    logger.trace("Dollars used: {dollars_used}", dollars_used=dollars_used)
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
        return count_anthropic_tokens(text)

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

    async def count_tokens_api(self, prompt: str, is_caching_enabled: bool) -> int:
        """
        Call the count tokens API. This API is free, so we don't ensure resource limits before calling it.
        There are rate limits though: https://docs.anthropic.com/en/docs/build-with-claude/token-counting#pricing-and-rate-limits
        """

        self.assert_caching_enabled_if_offline(is_caching_enabled)

        frame: FrameType | None = None
        if is_caching_enabled:
            frame = inspect.currentframe()

        cache_key: str | None = None
        if is_caching_enabled:
            cache_key, cached_response = await self._get_from_count_tokens_cache(frame)

            if cached_response is not None:
                return cached_response.input_tokens

        self.assert_not_offline_if_cache_miss(prompt)

        non_system_messages, system_messages = _convert_prompt_to_anthropic_messages(prompt)

        with _anthropic_exception_manager():
            async with self._get_client() as client:
                raw_response = await client.messages.count_tokens(
                    model=self.model_info.model_name,
                    messages=non_system_messages,
                    system=system_messages,
                )

            response = CountTokensResponse(input_tokens=raw_response.input_tokens)
            result = CachedCountTokensResponse(
                response=response,
                inputs=(
                    CountTokensInputs(model=self.model_info.model_name, prompt=prompt)
                    if self.is_caching_inputs
                    else None
                ),
            )

            if is_caching_enabled:
                assert cache_key is not None
                async with self.get_count_tokens_response_cache() as cache:
                    await cache.set(cache_key, result)

            return response.input_tokens

    def calculate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        caching_info: CachingInfo | None = None,
    ) -> float:
        try:
            # find the cost for the prompt, broken down into cache writes and regular input tokens

            # if we don't have the caching info, use the basic cost model (we catch the error below)
            if (
                caching_info is None
                or caching_info.provider_specific_data is None
                or self.model_info.provider_specific_info is None
            ):
                raise MissingCachingInfoError(
                    f"Missing required info for more precise cost estimates; caching info: {caching_info}, model info: {self.model_info.provider_specific_info}"
                )
            anthropic_caching_usage = caching_info.provider_specific_data
            assert isinstance(anthropic_caching_usage, AnthropicCachingInfo), "Expected AnthropicCachingInfo"
            anthropic_caching_rates = self.model_info.provider_specific_info
            assert isinstance(anthropic_caching_rates, AnthropicModelInfo), "Expected AnthropicModelInfo"
            cache_write_5m_tokens = anthropic_caching_usage.written_5m
            cache_write_1h_tokens = anthropic_caching_usage.written_1h
            cache_read_tokens = caching_info.read_from_cache
            regular_input_tokens = prompt_tokens - cache_write_5m_tokens - cache_write_1h_tokens

            input_cost = (
                cache_write_5m_tokens * anthropic_caching_rates.cost_per_5m_cache_write_token
                + cache_write_1h_tokens * anthropic_caching_rates.cost_per_1h_cache_write_token
                + cache_read_tokens * anthropic_caching_rates.cost_per_cache_read_token
                + regular_input_tokens * self.model_info.cost_per_input_token
            )

            output_cost = completion_tokens * self.model_info.cost_per_output_token

            return input_cost + output_cost

        except MissingCachingInfoError as e:
            logger.debug("{}; using basic cost model", e)
            return self.basic_calculate_cost(prompt_tokens, completion_tokens)


def _get_api_key_or_auth_token() -> tuple[str | None, str | None]:
    api_key = get_secret("ANTHROPIC_API_KEY")
    auth_token = get_secret("ANTHROPIC_AUTH_TOKEN")
    if not api_key and not auth_token:
        raise MissingAPIKeyError("Neither ANTHROPIC_API_KEY nor ANTHROPIC_AUTH_TOKEN environment variable is set")
    return api_key, auth_token


_CLAUDE_CODE_SYSTEM_PROMPT = TextBlockParam(
    type="text",
    text="You are Claude Code, Anthropic's official CLI for Claude.",
    cache_control=CacheControlEphemeralParam(type="ephemeral"),
)


def prepend_claude_code_system_prompt(
    system_prompt: str | list[TextBlockParam] | None,
) -> list[TextBlockParam]:
    """Prepends the system prompt used by Claude Code.

    When using the Claude API through Claude Pro/Max subscriptions,
    the Claude API requires this particular system prompt to be set;
    otherwise the request will fail.

    For simplicity and consistency,
    we always do this even when it's not strictly required,
    (like when using the Claude API through API keys).
    """
    if not system_prompt:
        return [_CLAUDE_CODE_SYSTEM_PROMPT]
    elif isinstance(system_prompt, str):
        return [
            _CLAUDE_CODE_SYSTEM_PROMPT,
            TextBlockParam(type="text", text=system_prompt),
        ]
    else:
        return [_CLAUDE_CODE_SYSTEM_PROMPT] + system_prompt
