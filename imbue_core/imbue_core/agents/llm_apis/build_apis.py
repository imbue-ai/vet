from pathlib import Path

from imbue_core.agents.configs import LanguageModelGenerationConfig
from imbue_core.agents.configs import MockedLanguageModelGenerationConfig
from imbue_core.agents.configs import OpenAICompatibleModelConfig
from imbue_core.agents.llm_apis.anthropic_api import AnthropicAPI
from imbue_core.agents.llm_apis.anthropic_api import AnthropicModelName
from imbue_core.agents.llm_apis.constants import approximate_token_count
from imbue_core.agents.llm_apis.gemini_api import GeminiAPI
from imbue_core.agents.llm_apis.gemini_api import GeminiModelName
from imbue_core.agents.llm_apis.groq_api import GroqChatAPI
from imbue_core.agents.llm_apis.groq_api import GroqSupportedModelName
from imbue_core.agents.llm_apis.language_model_api import LanguageModelAPI
from imbue_core.agents.llm_apis.mock_api import FileBasedLanguageModelMock
from imbue_core.agents.llm_apis.mock_api import MockModelName
from imbue_core.agents.llm_apis.openai_api import OpenAIChatAPI
from imbue_core.agents.llm_apis.openai_api import OpenAIModelName
from imbue_core.agents.llm_apis.openai_compatible_api import OpenAICompatibleAPI
from imbue_core.agents.llm_apis.together_api import TogetherAIModelName
from imbue_core.agents.llm_apis.together_api import TogetherAPI


def build_language_model_from_config(
    config: LanguageModelGenerationConfig,
) -> LanguageModelAPI:
    if isinstance(config, MockedLanguageModelGenerationConfig):
        return FileBasedLanguageModelMock(cache_path=config.mock_responses_path)

    if isinstance(config, OpenAICompatibleModelConfig):
        return OpenAICompatibleAPI(
            model_name=config.model_name,
            base_url=config.custom_base_url,
            api_key_env=config.custom_api_key_env,
            context_window=config.custom_context_window,
            max_output_tokens=config.custom_max_output_tokens,
            cache_path=config.cache_path,
            is_caching_inputs=config.is_caching_inputs,
            is_running_offline=config.is_running_offline,
            is_conversational=True,
            retry_jitter_factor=config.retry_jitter_factor,
        )

    if config.model_name in (v for v in MockModelName):
        return FileBasedLanguageModelMock(cache_path=config.cache_path)
    if config.model_name in (v for v in OpenAIModelName):
        return OpenAIChatAPI(
            model_name=config.model_name,
            cache_path=config.cache_path,
            is_caching_inputs=config.is_caching_inputs,
            is_running_offline=config.is_running_offline,
            is_conversational=True,
            is_using_logprobs=config.is_using_logprobs,
            retry_jitter_factor=config.retry_jitter_factor,
        )
    if config.model_name in (v for v in GroqSupportedModelName):
        return GroqChatAPI(
            model_name=config.model_name,
            cache_path=config.cache_path,
            is_caching_inputs=config.is_caching_inputs,
            is_running_offline=config.is_running_offline,
            is_conversational=True,
            is_using_logprobs=config.is_using_logprobs,
            retry_jitter_factor=config.retry_jitter_factor,
        )
    if config.model_name in (v for v in AnthropicModelName):
        return AnthropicAPI(
            model_name=config.model_name,
            cache_path=config.cache_path,
            count_tokens_cache_path=config.count_tokens_cache_path,
            is_caching_inputs=config.is_caching_inputs,
            is_running_offline=config.is_running_offline,
            is_conversational=True,
            is_using_logprobs=config.is_using_logprobs,
            retry_jitter_factor=config.retry_jitter_factor,
        )
    if config.model_name in (v for v in TogetherAIModelName):
        return TogetherAPI(
            model_name=config.model_name,
            cache_path=config.cache_path,
            # count tokens is not supported for Together API
            # count_tokens_cache_path=config.count_tokens_cache_path,
            is_caching_inputs=config.is_caching_inputs,
            is_running_offline=config.is_running_offline,
            is_conversational=True,
            is_using_logprobs=config.is_using_logprobs,
            retry_jitter_factor=config.retry_jitter_factor,
        )
    if config.model_name in (v for v in GeminiModelName):
        return GeminiAPI(
            model_name=config.model_name,
            cache_path=config.cache_path,
            count_tokens_cache_path=config.count_tokens_cache_path,
            is_caching_inputs=config.is_caching_inputs,
            is_running_offline=config.is_running_offline,
            is_conversational=True,
            is_using_logprobs=config.is_using_logprobs,
            retry_jitter_factor=config.retry_jitter_factor,
        )
    # if config.model_name in MISTRAL_CHAT_MODEL_NAMES:
    #     return MistralChatAPI(
    #         model_name=config.model_name,
    #         cache_path=config.cache_path,
    #         is_conversational=True,
    #     )

    raise NotImplementedError(f"{config.model_name} not supported by LanguageModelAPI")


def build_language_model_by_name(
    model_name: str,
    cache_path: Path | None = None,
    is_caching_inputs: bool = False,
    is_using_logprobs: bool = False,
) -> LanguageModelAPI:
    config = LanguageModelGenerationConfig(
        model_name=model_name,
        cache_path=cache_path,
        is_caching_inputs=is_caching_inputs,
        is_using_logprobs=is_using_logprobs,
    )
    return build_language_model_from_config(config)


def get_token_count_for_text_and_model(text: str, model_name: str) -> int:
    try:
        return build_language_model_by_name(model_name).count_tokens(text)
    except NotImplementedError:
        return approximate_token_count(text)
