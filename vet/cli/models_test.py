from __future__ import annotations

import pytest

from vet.cli.config.schema import ModelConfig
from vet.cli.config.schema import ModelsConfig
from vet.cli.config.schema import ProviderConfig
from vet.cli.models import DEFAULT_MODEL_ID
from vet.cli.models import get_agentic_models_by_provider
from vet.cli.models import get_all_model_ids
from vet.cli.models import get_builtin_model_ids
from vet.cli.models import get_builtin_models_by_provider
from vet.cli.models import get_models_by_provider
from vet.cli.models import is_user_defined_model
from vet.cli.models import is_valid_model_id
from vet.cli.models import validate_model_id
from vet.imbue_core.agents.agent_api.api import get_supported_providers_for_harness
from vet.imbue_core.agents.agent_api.claude.client import ClaudeCodeClient
from vet.imbue_core.agents.agent_api.codex.client import CodexClient
from vet.imbue_core.data_types import AgentHarnessType

SAMPLE_USER_CONFIG = ModelsConfig(
    providers={
        "custom": ProviderConfig(
            base_url="http://localhost:8080/v1",
            api_key_env="CUSTOM_KEY",
            models={
                "my-custom-model": ModelConfig(
                    context_window=128000,
                    max_output_tokens=16384,
                    supports_temperature=True,
                ),
                "another-model": ModelConfig(
                    context_window=128000,
                    max_output_tokens=16384,
                    supports_temperature=True,
                ),
            },
        )
    }
)


def test_default_model_is_in_builtin_models() -> None:
    assert DEFAULT_MODEL_ID in get_builtin_model_ids()


def test_get_builtin_model_ids_returns_strings() -> None:
    model_ids = get_builtin_model_ids()
    assert all(isinstance(m, str) for m in model_ids)


def test_get_all_model_ids_returns_builtin_models_when_no_config() -> None:
    all_ids = get_all_model_ids(user_config=None)
    builtin_ids = get_builtin_model_ids()
    assert all_ids == builtin_ids


def test_get_all_model_ids_includes_user_defined_models() -> None:
    all_ids = get_all_model_ids(SAMPLE_USER_CONFIG)

    assert "my-custom-model" in all_ids
    assert "another-model" in all_ids
    assert DEFAULT_MODEL_ID in all_ids


@pytest.mark.parametrize(
    ("model_id", "user_config", "expected"),
    [
        (DEFAULT_MODEL_ID, None, True),
        ("nonexistent-model-xyz", None, False),
        ("my-custom-model", SAMPLE_USER_CONFIG, True),
    ],
)
def test_is_valid_model_id(model_id: str, user_config: ModelsConfig | None, expected: bool) -> None:
    assert is_valid_model_id(model_id, user_config) is expected


@pytest.mark.parametrize(
    ("model_id", "user_config", "expected"),
    [
        ("any-model", None, False),
        ("my-custom-model", SAMPLE_USER_CONFIG, True),
        (DEFAULT_MODEL_ID, SAMPLE_USER_CONFIG, False),
    ],
)
def test_is_user_defined_model(model_id: str, user_config: ModelsConfig | None, expected: bool) -> None:
    assert is_user_defined_model(model_id, user_config) is expected


def test_validate_model_id_returns_model_id_when_valid() -> None:
    result = validate_model_id(DEFAULT_MODEL_ID)
    assert result == DEFAULT_MODEL_ID


def test_validate_model_id_raises_for_invalid_model() -> None:
    with pytest.raises(ValueError) as exc_info:
        validate_model_id("nonexistent-model-xyz")

    assert "Unknown model: nonexistent-model-xyz" in str(exc_info.value)
    assert "--list-models" in str(exc_info.value)


def test_validate_model_id_validates_user_defined_model() -> None:
    user_config = ModelsConfig(
        providers={
            "custom": ProviderConfig(
                base_url="http://localhost:8080/v1",
                api_key_env="CUSTOM_KEY",
                models={
                    "my-custom-model": ModelConfig(
                        context_window=128000,
                        max_output_tokens=16384,
                        supports_temperature=True,
                    )
                },
            )
        }
    )

    result = validate_model_id("my-custom-model", user_config)
    assert result == "my-custom-model"


def test_get_builtin_models_by_provider_returns_dict_with_expected_providers() -> None:
    providers = get_builtin_models_by_provider()

    assert "anthropic" in providers
    assert "openai" in providers
    assert "gemini" in providers
    assert "groq" in providers


def test_get_builtin_models_by_provider_all_values_are_lists_of_strings() -> None:
    providers = get_builtin_models_by_provider()

    for provider_name, models in providers.items():
        assert isinstance(models, list), f"{provider_name} should have a list of models"
        assert all(isinstance(m, str) for m in models), f"{provider_name} models should all be strings"


def test_get_models_by_provider_returns_builtin_providers_when_no_config() -> None:
    providers = get_models_by_provider(user_config=None)
    builtin_providers = get_builtin_models_by_provider()

    assert providers == builtin_providers


def test_get_models_by_provider_includes_user_defined_providers() -> None:
    user_config = ModelsConfig(
        providers={
            "ollama": ProviderConfig(
                name="Ollama Local",
                base_url="http://localhost:11434/v1",
                api_key_env="OLLAMA_KEY",
                models={
                    "llama3.2:latest": ModelConfig(
                        context_window=128000,
                        max_output_tokens=16384,
                        supports_temperature=True,
                    ),
                    "qwen:7b": ModelConfig(
                        context_window=32768,
                        max_output_tokens=8192,
                        supports_temperature=True,
                    ),
                },
            )
        }
    )

    providers = get_models_by_provider(user_config)

    assert "Ollama Local" in providers
    assert set(providers["Ollama Local"]) == {"llama3.2:latest", "qwen:7b"}
    assert "anthropic" in providers
    assert "openai" in providers


def test_get_models_by_provider_user_provider_overrides_builtin_with_same_name() -> None:
    user_config = ModelsConfig(
        providers={
            "custom": ProviderConfig(
                name="anthropic",
                base_url="http://localhost:8080/v1",
                api_key_env="CUSTOM_KEY",
                models={
                    "custom-model": ModelConfig(
                        context_window=128000,
                        max_output_tokens=16384,
                        supports_temperature=True,
                    )
                },
            )
        }
    )

    providers = get_models_by_provider(user_config)

    assert providers["anthropic"] == ["custom-model"]


# --- supported_providers() on concrete clients ---


def test_claude_code_client_supported_providers() -> None:
    assert ClaudeCodeClient.supported_providers() == ("anthropic",)


def test_codex_client_supported_providers() -> None:
    assert CodexClient.supported_providers() == ("openai",)


# --- get_supported_providers_for_harness ---


def test_get_supported_providers_for_claude_harness() -> None:
    providers = get_supported_providers_for_harness(AgentHarnessType.CLAUDE)
    assert providers == ("anthropic",)


def test_get_supported_providers_for_codex_harness() -> None:
    providers = get_supported_providers_for_harness(AgentHarnessType.CODEX)
    assert providers == ("openai",)


# --- get_agentic_models_by_provider ---


def test_get_agentic_models_for_claude_harness_returns_only_anthropic() -> None:
    providers = get_agentic_models_by_provider(AgentHarnessType.CLAUDE)

    assert "anthropic" in providers
    assert "openai" not in providers
    assert "gemini" not in providers
    assert "groq" not in providers


def test_get_agentic_models_for_codex_harness_returns_only_openai() -> None:
    providers = get_agentic_models_by_provider(AgentHarnessType.CODEX)

    assert "openai" in providers
    assert "anthropic" not in providers
    assert "gemini" not in providers
    assert "groq" not in providers


def test_get_agentic_models_values_are_lists_of_strings() -> None:
    for harness_type in AgentHarnessType:
        providers = get_agentic_models_by_provider(harness_type)
        for provider_name, models in providers.items():
            assert isinstance(models, list), f"{provider_name} should have a list of models"
            assert all(isinstance(m, str) for m in models), f"{provider_name} models should all be strings"


def test_get_agentic_models_is_subset_of_all_builtin_models() -> None:
    all_providers = get_builtin_models_by_provider()

    for harness_type in AgentHarnessType:
        agentic_providers = get_agentic_models_by_provider(harness_type)
        for provider_name, models in agentic_providers.items():
            assert provider_name in all_providers, f"{provider_name} should be a builtin provider"
            assert set(models) == set(all_providers[provider_name])
