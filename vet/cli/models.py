from __future__ import annotations

import os

from vet.cli.config.loader import get_model_ids_from_config
from vet.cli.config.loader import get_models_by_provider_from_config
from vet.cli.config.loader import get_provider_for_model
from vet.cli.config.schema import ModelsConfig
from vet.cli.config.schema import ProviderConfig
from vet.imbue_core.agents.llm_apis.anthropic_api import AnthropicModelName
from vet.imbue_core.agents.llm_apis.common import get_all_model_names
from vet.imbue_core.agents.llm_apis.gemini_api import GeminiModelName
from vet.imbue_core.agents.llm_apis.openai_api import OpenAIModelName

DEFAULT_MODEL_ID = AnthropicModelName.CLAUDE_4_6_OPUS.value


class MissingProviderAPIKeyError(Exception):
    def __init__(self, env_var: str, provider_name: str, model_id: str) -> None:
        self.env_var = env_var
        self.provider_name = provider_name
        self.model_id = model_id
        super().__init__(
            f"API key not found: environment variable '{env_var}' is not set. "
            + f"This is required for model '{model_id}' from provider '{provider_name}'."
        )


def get_builtin_model_ids() -> set[str]:
    return {str(name) for name in get_all_model_names()}


def get_all_model_ids(
    user_config: ModelsConfig | None = None,
    registry_config: ModelsConfig | None = None,
) -> set[str]:
    model_ids = get_builtin_model_ids()

    if user_config:
        model_ids.update(get_model_ids_from_config(user_config))

    if registry_config:
        model_ids.update(get_model_ids_from_config(registry_config))

    return model_ids


def is_valid_model_id(
    model_id: str,
    user_config: ModelsConfig | None = None,
    registry_config: ModelsConfig | None = None,
) -> bool:
    return model_id in get_all_model_ids(user_config, registry_config)


def validate_model_id(
    model_id: str,
    user_config: ModelsConfig | None = None,
    registry_config: ModelsConfig | None = None,
) -> str:
    if not is_valid_model_id(model_id, user_config, registry_config):
        raise ValueError(f"Unknown model: {model_id}. Use --list-models to see available models.")
    return model_id


def get_builtin_models_by_provider() -> dict[str, list[str]]:
    return {
        "anthropic": [m.value for m in AnthropicModelName],
        "openai": [m.value for m in OpenAIModelName],
        "gemini": [m.value for m in GeminiModelName],
    }


def get_models_by_provider(
    user_config: ModelsConfig | None = None,
    registry_config: ModelsConfig | None = None,
) -> dict[str, list[str]]:
    providers: dict[str, list[str]] = {}

    def _merge(source: dict[str, list[str]]) -> None:
        for name, models in source.items():
            if name in providers:
                seen = set(providers[name])
                providers[name].extend(m for m in models if m not in seen)
            else:
                providers[name] = list(models)

    if registry_config:
        _merge(get_models_by_provider_from_config(registry_config))

    _merge(get_builtin_models_by_provider())

    if user_config:
        _merge(get_models_by_provider_from_config(user_config))

    return providers


def _resolve_provider(
    model_id: str,
    user_config: ModelsConfig,
    registry_config: ModelsConfig | None = None,
) -> ProviderConfig | None:
    provider = get_provider_for_model(model_id, user_config)
    if provider is not None:
        return provider

    if model_id in get_builtin_model_ids():
        return None

    if registry_config is not None:
        return get_provider_for_model(model_id, registry_config)

    return None


def validate_api_key_for_model(
    model_id: str,
    user_config: ModelsConfig,
    registry_config: ModelsConfig | None = None,
) -> None:
    provider = _resolve_provider(model_id, user_config, registry_config)

    if provider is None:
        return

    api_key_env = provider.api_key_env
    if api_key_env is None:
        return

    api_key = os.environ.get(api_key_env, "")
    if not api_key:
        provider_name = provider.name or "unknown provider"
        raise MissingProviderAPIKeyError(
            env_var=api_key_env,
            provider_name=provider_name,
            model_id=model_id,
        )


def get_max_output_tokens_for_model(
    model_id: str,
    user_config: ModelsConfig,
    registry_config: ModelsConfig | None = None,
) -> int | None:
    provider = _resolve_provider(model_id, user_config, registry_config)
    if provider is not None:
        return provider.models[model_id].max_output_tokens

    try:
        from vet.imbue_core.agents.llm_apis.common import get_model_max_output_tokens

        return get_model_max_output_tokens(model_id)
    except Exception:
        return None


def build_language_model_config(
    model_id: str,
    user_config: ModelsConfig,
    registry_config: ModelsConfig | None = None,
):
    from vet.imbue_core.agents.configs import LanguageModelGenerationConfig
    from vet.imbue_core.agents.configs import OpenAICompatibleModelConfig

    provider = _resolve_provider(model_id, user_config, registry_config)

    if provider is None:
        return LanguageModelGenerationConfig(model_name=model_id)

    model_config = provider.models[model_id]
    actual_model_name = model_config.model_id or model_id

    return OpenAICompatibleModelConfig(
        model_name=actual_model_name,
        custom_base_url=provider.base_url,
        custom_api_key_env=provider.api_key_env or "",
        custom_context_window=model_config.context_window,
        custom_max_output_tokens=model_config.max_output_tokens,
        custom_supports_temperature=model_config.supports_temperature,
    )
