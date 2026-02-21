from pathlib import Path
from typing import Any
from typing import assert_never

from vet.imbue_core.agents.llm_apis.anthropic_api import AnthropicModelName
from vet.imbue_core.agents.llm_apis.anthropic_api import count_anthropic_tokens
from vet.imbue_core.agents.llm_apis.common import get_model_max_context_length
from vet.imbue_core.agents.llm_apis.constants import approximate_token_count
from vet.imbue_core.agents.llm_apis.data_types import ModelStr
from vet.imbue_core.agents.llm_apis.mock_api import MY_MOCK_MODEL_INFO
from vet.imbue_core.agents.llm_apis.openai_api import OpenAIModelName
from vet.imbue_core.agents.llm_apis.openai_api import count_openai_tokens
from vet.imbue_core.language_model_mode import LanguageModelMode
from vet.imbue_core.pydantic_serialization import SerializableModel


class LanguageModelGenerationConfig(SerializableModel):
    model_name: ModelStr = OpenAIModelName.GPT_4O_2024_08_06
    # this should almost always be None (you dont want to save your cache path into the hammer invocation data!)
    cache_path: Path | None = None
    count_tokens_cache_path: Path | None = None
    is_prompt_debugging_enabled: bool = False

    # If true, the LLM API will cache the inputs to the LLM call as well as the outputs, which makes prompt diffing easier.
    is_caching_inputs: bool = False

    # if this is set, the LLM API will return ONLY cached responses
    is_running_offline: bool = False

    # if set, the LLM API will return log probabilities for the output tokens (if supported by the model)
    is_using_logprobs: bool = False

    # Retry configuration
    retry_jitter_factor: float = 0.5

    def model_post_init(self, __context: Any) -> None:
        super().model_post_init(__context)
        # FIXME: do proper validation
        if self.cache_path is None and self.is_caching_inputs:
            raise ValueError("cache_path must be provided if is_caching_inputs is True")

    def count_tokens(self, text: str) -> int:
        """Count tokens in the given text using the model's tokenizer."""
        if self.model_name in (v for v in OpenAIModelName):
            return count_openai_tokens(text, self.model_name)
        if self.model_name in (v for v in AnthropicModelName):
            return count_anthropic_tokens(text)
        return approximate_token_count(text)

    def get_max_context_length(self) -> int:
        """Get the maximum context length for this model."""
        return get_model_max_context_length(self.model_name)

    def is_custom_model(self) -> bool:
        """Return True if this is a custom/user-defined model.

        Custom models use approximate token counting since there's no mechanism
        for defining a tokenizer for them.
        """
        return False


class OpenAICompatibleModelConfig(LanguageModelGenerationConfig):
    """Configuration for custom models using OpenAI-compatible APIs (e.g., Ollama, local LLMs)."""

    custom_base_url: str
    custom_api_key_env: str
    custom_context_window: int
    custom_max_output_tokens: int
    custom_supports_temperature: bool = True

    def count_tokens(self, text: str) -> int:
        """Count tokens using approximation since we don't have access to the model's tokenizer."""
        return approximate_token_count(text)

    def get_max_context_length(self) -> int:
        """Get the maximum context length for this model."""
        return self.custom_context_window

    def is_custom_model(self) -> bool:
        """Return True if this is a custom/user-defined model.

        Custom models use approximate token counting since there's no mechanism
        for defining a tokenizer for them.
        """
        # TODO: Support custom tokenizers with custom models.
        return True


class MockedLanguageModelGenerationConfig(LanguageModelGenerationConfig):
    model_name: ModelStr = MY_MOCK_MODEL_INFO.model_name
    is_running_offline: bool = True
    mock_responses_path: Path


def create_safe_llm_config(
    llm_name: ModelStr, mode: LanguageModelMode, cache_path: Path | None = None
) -> LanguageModelGenerationConfig:
    match mode:
        case LanguageModelMode.LIVE:
            assert cache_path is None
            language_model_config = LanguageModelGenerationConfig(model_name=llm_name)
        case LanguageModelMode.OFFLINE:
            assert cache_path is not None
            language_model_config = LanguageModelGenerationConfig(
                model_name=llm_name,
                is_running_offline=True,
                is_caching_inputs=True,
                cache_path=cache_path,
            )
        case LanguageModelMode.UPDATE_SNAPSHOT:
            assert cache_path is not None
            language_model_config = LanguageModelGenerationConfig(
                model_name=llm_name, is_caching_inputs=True, cache_path=cache_path
            )
        case LanguageModelMode.MOCKED:
            assert cache_path is not None
            language_model_config = MockedLanguageModelGenerationConfig(
                model_name=llm_name, mock_responses_path=cache_path
            )
        case _ as unreachable:
            assert_never(unreachable)  # pyre-ignore[6]: pyre doesn't understand enums
            assert False  # because pyre doesn't really understand assert_never, either
    return language_model_config
