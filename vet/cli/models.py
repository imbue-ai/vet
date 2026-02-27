from __future__ import annotations

from vet.cli.config.loader import get_model_ids_from_config
from vet.cli.config.loader import get_models_by_provider_from_config
from vet.cli.config.schema import ModelsConfig
from vet.imbue_core.agents.llm_apis.anthropic_api import AnthropicModelName
from vet.imbue_core.agents.llm_apis.common import get_all_model_names
from vet.imbue_core.agents.llm_apis.gemini_api import GeminiModelName
from vet.imbue_core.agents.llm_apis.openai_api import OpenAIModelName

DEFAULT_MODEL_ID = AnthropicModelName.CLAUDE_4_6_OPUS.value


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
    if registry_config:
        providers.update(get_models_by_provider_from_config(registry_config))

    providers.update(get_builtin_models_by_provider())

    if user_config:
        providers.update(get_models_by_provider_from_config(user_config))

    return providers
