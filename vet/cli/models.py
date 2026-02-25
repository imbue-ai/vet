from __future__ import annotations

from vet.cli.config.loader import get_models_by_provider_from_config
from vet.cli.config.loader import get_user_defined_model_ids
from vet.cli.config.schema import ModelsConfig
from vet.imbue_core.agents.llm_apis.anthropic_api import AnthropicModelName
from vet.imbue_core.agents.llm_apis.common import get_all_model_names
from vet.imbue_core.agents.llm_apis.gemini_api import GeminiModelName
from vet.imbue_core.agents.llm_apis.groq_api import GroqSupportedModelName
from vet.imbue_core.agents.llm_apis.openai_api import OpenAIModelName
from vet.imbue_core.data_types import AgentHarnessType

DEFAULT_MODEL_ID = AnthropicModelName.CLAUDE_4_6_OPUS.value


def get_builtin_model_ids() -> set[str]:
    return {str(name) for name in get_all_model_names()}


def get_all_model_ids(user_config: ModelsConfig | None = None) -> set[str]:
    model_ids = get_builtin_model_ids()

    if user_config:
        model_ids.update(get_user_defined_model_ids(user_config))

    return model_ids


def is_valid_model_id(model_id: str, user_config: ModelsConfig | None = None) -> bool:
    return model_id in get_all_model_ids(user_config)


def is_user_defined_model(model_id: str, user_config: ModelsConfig | None = None) -> bool:
    if user_config is None:
        return False
    return model_id in get_user_defined_model_ids(user_config)


def validate_model_id(model_id: str, user_config: ModelsConfig | None = None) -> str:
    if not is_valid_model_id(model_id, user_config):
        raise ValueError(f"Unknown model: {model_id}. Use --list-models to see available models.")
    return model_id


def get_builtin_models_by_provider() -> dict[str, list[str]]:
    return {
        "anthropic": [m.value for m in AnthropicModelName],
        "openai": [m.value for m in OpenAIModelName],
        "gemini": [m.value for m in GeminiModelName],
        "groq": [m.value for m in GroqSupportedModelName],
    }


def get_models_by_provider(
    user_config: ModelsConfig | None = None,
) -> dict[str, list[str]]:
    providers = get_builtin_models_by_provider()

    if user_config:
        user_providers = get_models_by_provider_from_config(user_config)
        for provider_name, model_ids in user_providers.items():
            providers[provider_name] = model_ids

    return providers


def get_agentic_models_by_provider(
    harness_type: AgentHarnessType,
) -> dict[str, list[str]]:
    """Return only the providers/models compatible with *harness_type*.

    In agentic mode the analysis is delegated to an external CLI (e.g. Claude
    Code or Codex) which only supports a subset of providers.  This function
    filters the built-in model registry to those providers.

    Note: the underlying CLIs will accept any model their API supports —
    including models not tracked in vet's built-in enums.  The list returned
    here is therefore a *representative* subset, not an exhaustive enumeration.
    """
    from vet.imbue_core.agents.agent_api.api import get_supported_providers_for_harness

    supported = set(get_supported_providers_for_harness(harness_type))
    all_providers = get_builtin_models_by_provider()
    return {name: models for name, models in all_providers.items() if name in supported}
