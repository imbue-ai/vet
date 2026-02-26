from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from vet.cli.config.loader import ConfigLoadError
from vet.cli.config.loader import MissingAPIKeyError
from vet.cli.config.loader import _load_single_config_file
from vet.cli.config.loader import _refresh_remote_registry_cache
from vet.cli.config.loader import build_language_model_config
from vet.cli.config.loader import find_git_repo_root
from vet.cli.config.loader import get_config_file_paths
from vet.cli.config.loader import get_models_by_provider_from_config
from vet.cli.config.loader import get_provider_for_model
from vet.cli.config.loader import get_user_defined_model_ids
from vet.cli.config.loader import get_xdg_config_home
from vet.cli.config.loader import load_models_config
from vet.cli.config.loader import load_registry_config
from vet.cli.config.loader import validate_api_key_for_model
from vet.cli.config.schema import ModelConfig
from vet.cli.config.schema import ModelsConfig
from vet.cli.config.schema import ProviderConfig


def test_get_xdg_config_home_uses_env_var(tmp_path: Path) -> None:
    with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(tmp_path)}):
        assert get_xdg_config_home() == tmp_path


def test_get_xdg_config_home_defaults_to_home_config() -> None:
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("XDG_CONFIG_HOME", None)
        result = get_xdg_config_home()
        assert result == Path.home() / ".config"


def test_find_git_repo_root_finds_root(tmp_path: Path) -> None:
    git_root = tmp_path / "repo"
    git_root.mkdir()
    (git_root / ".git").mkdir()
    subdir = git_root / "src" / "deep" / "nested"
    subdir.mkdir(parents=True)

    result = find_git_repo_root(subdir)
    assert result == git_root


def test_find_git_repo_root_returns_none_when_not_in_repo(tmp_path: Path) -> None:
    non_repo = tmp_path / "not_a_repo"
    non_repo.mkdir()

    result = find_git_repo_root(non_repo)
    assert result is None


def test_get_config_file_paths_returns_global_path(tmp_path: Path) -> None:
    with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(tmp_path)}):
        paths = get_config_file_paths(repo_path=None)
        assert len(paths) == 1
        assert paths[0] == tmp_path / "vet" / "models.json"


def test_get_config_file_paths_finds_git_root(tmp_path: Path) -> None:
    xdg_config = tmp_path / "xdg"
    git_root = tmp_path / "repo"
    git_root.mkdir()
    (git_root / ".git").mkdir()
    subdir = git_root / "src" / "submodule"
    subdir.mkdir(parents=True)

    with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg_config)}):
        paths = get_config_file_paths(repo_path=subdir)
        assert len(paths) == 2
        assert paths[0] == xdg_config / "vet" / "models.json"
        assert paths[1] == git_root / ".vet" / "models.json"


def test_load_single_config_file_loads_valid_config(tmp_path: Path) -> None:
    config_file = tmp_path / "models.json"
    config_data = {
        "providers": {
            "test-provider": {
                "name": "Test Provider",
                "api_type": "openai_compatible",
                "base_url": "http://localhost:8080/v1",
                "api_key_env": "TEST_API_KEY",
                "models": {
                    "test-model": {
                        "model_id": "test-model-v1",
                        "context_window": 128000,
                        "max_output_tokens": 16384,
                        "supports_temperature": True,
                    }
                },
            }
        }
    }
    config_file.write_text(json.dumps(config_data))

    result = _load_single_config_file(config_file)

    assert "test-provider" in result.providers
    provider = result.providers["test-provider"]
    assert provider.name == "Test Provider"
    assert provider.base_url == "http://localhost:8080/v1"
    assert provider.api_key_env == "TEST_API_KEY"
    assert "test-model" in provider.models
    assert provider.models["test-model"].model_id == "test-model-v1"


def test_load_single_config_file_raises_on_invalid_json(tmp_path: Path) -> None:
    config_file = tmp_path / "models.json"
    config_file.write_text("not valid json")

    with pytest.raises(ConfigLoadError) as exc_info:
        _load_single_config_file(config_file)
    assert "Invalid JSON" in str(exc_info.value)


def test_load_single_config_file_raises_on_invalid_schema(tmp_path: Path) -> None:
    config_file = tmp_path / "models.json"
    config_data = {
        "providers": {
            "test-provider": {
                "name": "Test Provider",
            }
        }
    }
    config_file.write_text(json.dumps(config_data))

    with pytest.raises(ConfigLoadError) as exc_info:
        _load_single_config_file(config_file)
    assert "Invalid configuration" in str(exc_info.value)


def test_load_single_config_file_raises_on_invalid_api_type(tmp_path: Path) -> None:
    config_file = tmp_path / "models.json"
    config_data = {
        "providers": {
            "test-provider": {
                "name": "Test Provider",
                "api_type": "anthropic",
                "base_url": "http://localhost:8080/v1",
                "api_key_env": "TEST_API_KEY",
                "models": {},
            }
        }
    }
    config_file.write_text(json.dumps(config_data))

    with pytest.raises(ConfigLoadError) as exc_info:
        _load_single_config_file(config_file)
    assert "Invalid configuration" in str(exc_info.value)


def test_load_models_config_returns_empty_when_no_files_exist(tmp_path: Path) -> None:
    with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(tmp_path / "nonexistent")}):
        result = load_models_config(repo_path=tmp_path)
        assert result.providers == {}


def test_load_models_config_loads_project_config(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    vet_dir = repo_path / ".vet"
    vet_dir.mkdir()
    config_file = vet_dir / "models.json"
    config_data = {
        "providers": {
            "project-provider": {
                "base_url": "http://project:8080/v1",
                "api_key_env": "PROJECT_KEY",
                "models": {
                    "project-model": {
                        "context_window": 128000,
                        "max_output_tokens": 16384,
                        "supports_temperature": True,
                    }
                },
            }
        }
    }
    config_file.write_text(json.dumps(config_data))

    with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(tmp_path / "nonexistent")}):
        result = load_models_config(repo_path=repo_path)

    assert "project-provider" in result.providers


def test_load_models_config_project_overrides_global(tmp_path: Path) -> None:
    xdg_config = tmp_path / "xdg"
    (xdg_config / "vet").mkdir(parents=True)
    global_config = xdg_config / "vet" / "models.json"
    global_config.write_text(
        json.dumps(
            {
                "providers": {
                    "shared-provider": {
                        "name": "Global Name",
                        "base_url": "http://global:8080/v1",
                        "api_key_env": "GLOBAL_KEY",
                        "models": {
                            "global-model": {
                                "context_window": 128000,
                                "max_output_tokens": 16384,
                                "supports_temperature": True,
                            }
                        },
                    }
                }
            }
        )
    )

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".vet").mkdir()
    project_config = repo_path / ".vet" / "models.json"
    project_config.write_text(
        json.dumps(
            {
                "providers": {
                    "shared-provider": {
                        "name": "Project Name",
                        "base_url": "http://project:8080/v1",
                        "api_key_env": "PROJECT_KEY",
                        "models": {
                            "project-model": {
                                "context_window": 128000,
                                "max_output_tokens": 16384,
                                "supports_temperature": True,
                            }
                        },
                    }
                }
            }
        )
    )

    with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg_config)}):
        result = load_models_config(repo_path=repo_path)

    assert result.providers["shared-provider"].name == "Project Name"
    assert result.providers["shared-provider"].base_url == "http://project:8080/v1"


def test_get_user_defined_model_ids_extracts_all_ids() -> None:
    config = ModelsConfig(
        providers={
            "provider1": ProviderConfig(
                base_url="http://localhost:8080/v1",
                api_key_env="KEY1",
                models={
                    "model-a": ModelConfig(
                        context_window=128000,
                        max_output_tokens=16384,
                        supports_temperature=True,
                    ),
                    "model-b": ModelConfig(
                        context_window=128000,
                        max_output_tokens=16384,
                        supports_temperature=True,
                    ),
                },
            ),
            "provider2": ProviderConfig(
                base_url="http://localhost:8081/v1",
                api_key_env="KEY2",
                models={
                    "model-c": ModelConfig(
                        context_window=128000,
                        max_output_tokens=16384,
                        supports_temperature=True,
                    ),
                },
            ),
        }
    )

    result = get_user_defined_model_ids(config)

    assert result == {"model-a", "model-b", "model-c"}


def test_get_provider_for_model_finds_provider() -> None:
    config = ModelsConfig(
        providers={
            "provider1": ProviderConfig(
                base_url="http://localhost:8080/v1",
                api_key_env="KEY1",
                models={
                    "model-a": ModelConfig(
                        context_window=128000,
                        max_output_tokens=16384,
                        supports_temperature=True,
                    )
                },
            ),
            "provider2": ProviderConfig(
                base_url="http://localhost:8081/v1",
                api_key_env="KEY2",
                models={
                    "model-b": ModelConfig(
                        context_window=128000,
                        max_output_tokens=16384,
                        supports_temperature=True,
                    )
                },
            ),
        }
    )

    result = get_provider_for_model("model-b", config)

    assert result is not None
    assert result.api_key_env == "KEY2"


def test_get_provider_for_model_returns_none_for_unknown() -> None:
    config = ModelsConfig(
        providers={
            "provider1": ProviderConfig(
                base_url="http://localhost:8080/v1",
                api_key_env="KEY1",
                models={
                    "model-a": ModelConfig(
                        context_window=128000,
                        max_output_tokens=16384,
                        supports_temperature=True,
                    )
                },
            ),
        }
    )

    result = get_provider_for_model("unknown-model", config)

    assert result is None


def test_validate_api_key_passes_when_key_is_set() -> None:
    config = ModelsConfig(
        providers={
            "provider1": ProviderConfig(
                name="Test Provider",
                base_url="http://localhost:8080/v1",
                api_key_env="TEST_API_KEY",
                models={
                    "model-a": ModelConfig(
                        context_window=128000,
                        max_output_tokens=16384,
                        supports_temperature=True,
                    )
                },
            ),
        }
    )

    with patch.dict(os.environ, {"TEST_API_KEY": "secret-key"}):
        validate_api_key_for_model("model-a", config)


def test_validate_api_key_raises_when_key_not_set() -> None:
    config = ModelsConfig(
        providers={
            "provider1": ProviderConfig(
                name="Test Provider",
                base_url="http://localhost:8080/v1",
                api_key_env="MISSING_KEY",
                models={
                    "model-a": ModelConfig(
                        context_window=128000,
                        max_output_tokens=16384,
                        supports_temperature=True,
                    )
                },
            ),
        }
    )

    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("MISSING_KEY", None)
        with pytest.raises(MissingAPIKeyError) as exc_info:
            validate_api_key_for_model("model-a", config)

        assert exc_info.value.env_var == "MISSING_KEY"
        assert exc_info.value.model_id == "model-a"
        assert "MISSING_KEY" in str(exc_info.value)


def test_validate_api_key_passes_for_unknown_model() -> None:
    config = ModelsConfig(providers={})
    validate_api_key_for_model("unknown-model", config)


def test_get_models_by_provider_groups_models() -> None:
    config = ModelsConfig(
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
            ),
            "openrouter": ProviderConfig(
                base_url="https://openrouter.ai/api/v1",
                api_key_env="OPENROUTER_KEY",
                models={
                    "anthropic/claude-3": ModelConfig(
                        context_window=200000,
                        max_output_tokens=16384,
                        supports_temperature=True,
                    ),
                },
            ),
        }
    )

    result = get_models_by_provider_from_config(config)

    assert "Ollama Local" in result
    assert set(result["Ollama Local"]) == {"llama3.2:latest", "qwen:7b"}

    assert "openrouter" in result
    assert result["openrouter"] == ["anthropic/claude-3"]


# --- Remote registry tests ---

_REMOTE_PROVIDER_JSON = json.dumps(
    {
        "providers": {
            "remote-provider": {
                "base_url": "http://remote:8080/v1",
                "api_key_env": "REMOTE_KEY",
                "models": {
                    "remote-model": {
                        "context_window": 128000,
                        "max_output_tokens": 16384,
                        "supports_temperature": True,
                    }
                },
            }
        }
    }
)


def test_remote_registry_disabled_via_env(tmp_path: Path) -> None:
    with patch.dict(os.environ, {"VET_REMOTE_REGISTRY": "0", "XDG_CACHE_HOME": str(tmp_path)}):
        result = _refresh_remote_registry_cache()
    assert result is None


def test_remote_registry_disabled_via_false(tmp_path: Path) -> None:
    with patch.dict(os.environ, {"VET_REMOTE_REGISTRY": "false", "XDG_CACHE_HOME": str(tmp_path)}):
        result = _refresh_remote_registry_cache()
    assert result is None


def test_remote_registry_uses_fresh_cache(tmp_path: Path) -> None:
    cache_dir = tmp_path / "vet"
    cache_dir.mkdir(parents=True)
    cache_file = cache_dir / "remote_models.json"
    cache_file.write_text(_REMOTE_PROVIDER_JSON)

    env = {"XDG_CACHE_HOME": str(tmp_path), "VET_REMOTE_REGISTRY": "1"}
    with patch.dict(os.environ, env):
        with patch("vet.cli.config.loader.urllib.request.urlopen") as mock_urlopen:
            result = _refresh_remote_registry_cache()

    # Should not have made a network request — cache is fresh
    mock_urlopen.assert_not_called()
    assert result == cache_file


def test_remote_registry_fetches_when_no_cache(tmp_path: Path) -> None:
    env = {"XDG_CACHE_HOME": str(tmp_path), "VET_REMOTE_REGISTRY": "1"}

    mock_response = type(
        "Response",
        (),
        {
            "read": lambda self: _REMOTE_PROVIDER_JSON.encode(),
            "__enter__": lambda self: self,
            "__exit__": lambda *a: None,
        },
    )()

    with patch.dict(os.environ, env):
        with patch("vet.cli.config.loader.urllib.request.urlopen", return_value=mock_response):
            result = _refresh_remote_registry_cache()

    assert result is not None
    assert result.exists()
    assert json.loads(result.read_text())["providers"]["remote-provider"]


def test_remote_registry_fetches_when_cache_stale(tmp_path: Path) -> None:
    cache_dir = tmp_path / "vet"
    cache_dir.mkdir(parents=True)
    cache_file = cache_dir / "remote_models.json"
    cache_file.write_text('{"providers": {}}')
    # Make cache appear old
    old_time = time.time() - 100000
    os.utime(cache_file, (old_time, old_time))

    mock_response = type(
        "Response",
        (),
        {
            "read": lambda self: _REMOTE_PROVIDER_JSON.encode(),
            "__enter__": lambda self: self,
            "__exit__": lambda *a: None,
        },
    )()

    env = {"XDG_CACHE_HOME": str(tmp_path), "VET_REMOTE_REGISTRY": "1"}
    with patch.dict(os.environ, env):
        with patch("vet.cli.config.loader.urllib.request.urlopen", return_value=mock_response):
            result = _refresh_remote_registry_cache()

    assert result is not None
    # Cache should now contain the fresh data
    assert "remote-provider" in json.loads(result.read_text())["providers"]


def test_remote_registry_falls_back_to_stale_cache_on_error(tmp_path: Path) -> None:
    cache_dir = tmp_path / "vet"
    cache_dir.mkdir(parents=True)
    cache_file = cache_dir / "remote_models.json"
    cache_file.write_text(_REMOTE_PROVIDER_JSON)
    # Make cache stale
    old_time = time.time() - 100000
    os.utime(cache_file, (old_time, old_time))

    env = {"XDG_CACHE_HOME": str(tmp_path), "VET_REMOTE_REGISTRY": "1"}
    with patch.dict(os.environ, env):
        with patch(
            "vet.cli.config.loader.urllib.request.urlopen",
            side_effect=OSError("no network"),
        ):
            result = _refresh_remote_registry_cache()

    # Falls back to stale cache
    assert result == cache_file


def test_remote_registry_returns_none_on_error_without_cache(tmp_path: Path) -> None:
    env = {"XDG_CACHE_HOME": str(tmp_path), "VET_REMOTE_REGISTRY": "1"}
    with patch.dict(os.environ, env):
        with patch(
            "vet.cli.config.loader.urllib.request.urlopen",
            side_effect=OSError("no network"),
        ):
            result = _refresh_remote_registry_cache()

    assert result is None


def test_remote_registry_respects_custom_url(tmp_path: Path) -> None:
    custom_url = "https://example.com/custom/models.json"
    mock_response = type(
        "Response",
        (),
        {
            "read": lambda self: _REMOTE_PROVIDER_JSON.encode(),
            "__enter__": lambda self: self,
            "__exit__": lambda *a: None,
        },
    )()

    env = {
        "XDG_CACHE_HOME": str(tmp_path),
        "VET_REGISTRY_URL": custom_url,
        "VET_REMOTE_REGISTRY": "1",
    }
    with patch.dict(os.environ, env):
        with patch("vet.cli.config.loader.urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            _refresh_remote_registry_cache()

    # Verify the custom URL was used
    call_args = mock_urlopen.call_args
    assert call_args[0][0].full_url == custom_url


def test_load_models_config_does_not_include_registry(tmp_path: Path) -> None:
    """load_models_config only returns user-defined configs, not registry."""
    cache_dir = tmp_path / "cache" / "vet"
    cache_dir.mkdir(parents=True)
    cache_file = cache_dir / "remote_models.json"
    cache_file.write_text(
        json.dumps(
            {
                "providers": {
                    "remote-only": {
                        "base_url": "http://remote:8080/v1",
                        "models": {
                            "remote-model": {
                                "context_window": 64000,
                                "max_output_tokens": 8192,
                                "supports_temperature": True,
                            }
                        },
                    }
                }
            }
        )
    )

    env = {
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "XDG_CONFIG_HOME": str(tmp_path / "nonexistent"),
        "VET_REMOTE_REGISTRY": "1",
    }
    with patch.dict(os.environ, env):
        result = load_models_config(repo_path=None)

    # Registry providers should NOT be in load_models_config result
    assert "remote-only" not in result.providers


def test_load_registry_config_returns_registry_providers(tmp_path: Path) -> None:
    cache_dir = tmp_path / "vet"
    cache_dir.mkdir(parents=True)
    cache_file = cache_dir / "remote_models.json"
    cache_file.write_text(_REMOTE_PROVIDER_JSON)

    env = {"XDG_CACHE_HOME": str(tmp_path), "VET_REMOTE_REGISTRY": "1"}
    with patch.dict(os.environ, env):
        result = load_registry_config()

    assert "remote-provider" in result.providers


def test_load_registry_config_returns_empty_when_disabled(tmp_path: Path) -> None:
    env = {"XDG_CACHE_HOME": str(tmp_path), "VET_REMOTE_REGISTRY": "0"}
    with patch.dict(os.environ, env):
        result = load_registry_config()

    assert result.providers == {}


# --- Precedence tests ---


def _make_provider(base_url: str, model_id: str, api_key_env: str | None = None) -> ProviderConfig:
    return ProviderConfig(
        base_url=base_url,
        api_key_env=api_key_env,
        models={
            model_id: ModelConfig(
                context_window=128000,
                max_output_tokens=16384,
                supports_temperature=True,
            )
        },
    )


def test_build_config_user_defined_wins_over_builtin_and_registry() -> None:
    """User-defined model with a built-in ID should use user config (highest priority)."""
    from vet.imbue_core.agents.configs import OpenAICompatibleModelConfig
    from vet.imbue_core.agents.llm_apis.anthropic_api import AnthropicModelName

    builtin_id = AnthropicModelName.CLAUDE_4_6_OPUS.value
    user_config = ModelsConfig(providers={"custom": _make_provider("http://custom:8080/v1", builtin_id)})
    registry_config = ModelsConfig(providers={"registry": _make_provider("http://registry:8080/v1", builtin_id)})

    result = build_language_model_config(builtin_id, user_config, registry_config)
    assert isinstance(result, OpenAICompatibleModelConfig)
    assert result.custom_base_url == "http://custom:8080/v1"


def test_build_config_builtin_wins_over_registry() -> None:
    """A built-in model ID in the registry should NOT shadow the built-in."""
    from vet.imbue_core.agents.configs import LanguageModelGenerationConfig
    from vet.imbue_core.agents.llm_apis.anthropic_api import AnthropicModelName

    builtin_id = AnthropicModelName.CLAUDE_4_6_OPUS.value
    user_config = ModelsConfig(providers={})
    registry_config = ModelsConfig(providers={"registry": _make_provider("http://registry:8080/v1", builtin_id)})

    result = build_language_model_config(builtin_id, user_config, registry_config)
    # Should use native built-in path, not the registry's OpenAI-compatible path
    assert isinstance(result, LanguageModelGenerationConfig)
    assert result.model_name == builtin_id


def test_build_config_registry_used_for_unknown_model() -> None:
    """A registry-only model (not built-in, not user-defined) should use registry."""
    from vet.imbue_core.agents.configs import OpenAICompatibleModelConfig

    user_config = ModelsConfig(providers={})
    registry_config = ModelsConfig(
        providers={"registry": _make_provider("http://registry:8080/v1", "registry-only-model")}
    )

    result = build_language_model_config("registry-only-model", user_config, registry_config)
    assert isinstance(result, OpenAICompatibleModelConfig)
    assert result.custom_base_url == "http://registry:8080/v1"


def test_build_config_no_registry_falls_through() -> None:
    """Without registry, an unknown non-built-in model falls through to native path."""
    from vet.imbue_core.agents.configs import LanguageModelGenerationConfig

    user_config = ModelsConfig(providers={})
    result = build_language_model_config("totally-unknown", user_config)
    assert isinstance(result, LanguageModelGenerationConfig)
    assert result.model_name == "totally-unknown"
