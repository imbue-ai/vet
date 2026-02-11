from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import ValidationError

from vet.imbue_core.agents.configs import LanguageModelGenerationConfig
from vet.imbue_core.agents.configs import OpenAICompatibleModelConfig
from vet.imbue_core.agents.llm_apis.common import get_model_max_output_tokens
from vet.imbue_core.data_types import IssueCode
from vet.cli.config.cli_config_schema import CliConfigPreset
from vet.cli.config.cli_config_schema import merge_presets
from vet.cli.config.cli_config_schema import parse_cli_config_from_dict
from vet.cli.config.schema import CustomGuideConfig
from vet.cli.config.schema import CustomGuidesConfig
from vet.cli.config.schema import ModelsConfig
from vet.cli.config.schema import ProviderConfig


class ConfigLoadError(Exception):
    pass


class MissingAPIKeyError(Exception):
    def __init__(self, env_var: str, provider_name: str, model_id: str) -> None:
        self.env_var = env_var
        self.provider_name = provider_name
        self.model_id = model_id
        super().__init__(
            f"API key not found: environment variable '{env_var}' is not set. "
            + f"This is required for model '{model_id}' from provider '{provider_name}'."
        )


def get_xdg_config_home() -> Path:
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        return Path(xdg_config)
    return Path.home() / ".config"


def find_git_repo_root(start_path: Path) -> Path | None:
    current = start_path.resolve()
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    if (current / ".git").exists():
        return current
    return None


def _get_config_file_paths(
    global_subpath: str,
    global_filename: str,
    project_filename: str,
    repo_path: Path | None = None,
) -> list[Path]:
    paths = [get_xdg_config_home() / global_subpath / global_filename]

    if repo_path:
        git_root = find_git_repo_root(repo_path)
        root = git_root if git_root else repo_path
        paths.append(root / project_filename)

    return paths


def get_config_file_paths(repo_path: Path | None = None) -> list[Path]:
    return _get_config_file_paths("vet", "models.json", "models.json", repo_path)


def _load_single_config_file(config_path: Path) -> ModelsConfig:
    try:
        with open(config_path) as f:
            return ModelsConfig.model_validate_json(f.read())
    except ValidationError as e:
        raise ConfigLoadError(f"Invalid configuration in {config_path}: {e}") from e
    except OSError as e:
        raise ConfigLoadError(f"Cannot read {config_path}: {e}") from e


def load_models_config(repo_path: Path | None = None) -> ModelsConfig:
    merged_providers: dict[str, ProviderConfig] = {}

    for config_path in get_config_file_paths(repo_path):
        if config_path.exists():
            config = _load_single_config_file(config_path)
            merged_providers.update(config.providers)

    return ModelsConfig(providers=merged_providers)


def get_user_defined_model_ids(config: ModelsConfig) -> set[str]:
    model_ids: set[str] = set()
    for provider in config.providers.values():
        model_ids.update(provider.models.keys())
    return model_ids


def get_provider_for_model(model_id: str, config: ModelsConfig) -> ProviderConfig | None:
    for provider in config.providers.values():
        if model_id in provider.models:
            return provider
    return None


def validate_api_key_for_model(model_id: str, config: ModelsConfig) -> None:
    provider = get_provider_for_model(model_id, config)
    if provider is None:
        return

    api_key_env = provider.api_key_env
    if api_key_env is None:
        return

    api_key = os.environ.get(api_key_env, "")
    if not api_key:
        provider_name = provider.name or "unknown provider"
        raise MissingAPIKeyError(
            env_var=api_key_env,
            provider_name=provider_name,
            model_id=model_id,
        )


def get_models_by_provider_from_config(config: ModelsConfig) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for provider_id, provider in config.providers.items():
        display_name = provider.name or provider_id
        result[display_name] = list(provider.models.keys())
    return result


def get_max_output_tokens_for_model(model_id: str, config: ModelsConfig) -> int | None:
    provider = get_provider_for_model(model_id, config)
    if provider is not None:
        return provider.models[model_id].max_output_tokens

    try:
        return get_model_max_output_tokens(model_id)
    except Exception:
        return None


def build_language_model_config(model_id: str, user_config: ModelsConfig) -> LanguageModelGenerationConfig:
    provider = get_provider_for_model(model_id, user_config)
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
    )


def get_cli_config_file_paths(repo_path: Path | None = None) -> list[Path]:
    return _get_config_file_paths("vet", "config.toml", "vet.toml", repo_path)


def _load_cli_config_file(config_path: Path) -> dict[str, CliConfigPreset]:
    try:
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        return parse_cli_config_from_dict(data)
    except tomllib.TOMLDecodeError as e:
        raise ConfigLoadError(f"Invalid TOML in {config_path}: {e}") from e
    except ValidationError as e:
        raise ConfigLoadError(f"Invalid configuration in {config_path}: {e}") from e
    except OSError as e:
        raise ConfigLoadError(f"Cannot read {config_path}: {e}") from e


def load_cli_config(repo_path: Path | None = None) -> dict[str, CliConfigPreset]:
    merged_configs: dict[str, CliConfigPreset] = {}

    for config_path in get_cli_config_file_paths(repo_path):
        if config_path.exists():
            file_configs = _load_cli_config_file(config_path)
            for name, preset in file_configs.items():
                if name in merged_configs:
                    merged_configs[name] = merge_presets(merged_configs[name], preset)
                else:
                    merged_configs[name] = preset

    return merged_configs


def get_config_preset(
    config_name: str,
    cli_configs: dict[str, CliConfigPreset],
    repo_path: Path | None = None,
) -> CliConfigPreset:
    if config_name not in cli_configs:
        available = sorted(cli_configs.keys())
        if available:
            raise ConfigLoadError(f"Configuration '{config_name}' not found. Available configs: {', '.join(available)}")
        else:
            paths = get_cli_config_file_paths(repo_path)
            paths_list = "\n".join(f"  - {p} ({'global' if i == 0 else 'project'})" for i, p in enumerate(paths))
            raise ConfigLoadError(
                f"Configuration '{config_name}' not found.\n\n"
                f"No configuration files found. Create a config at one of these locations:\n{paths_list}"
            )
    return cli_configs[config_name]


def get_guides_config_file_paths(repo_path: Path | None = None) -> list[Path]:
    return _get_config_file_paths("vet", "guides.toml", "guides.toml", repo_path)


def _load_single_guides_file(config_path: Path) -> CustomGuidesConfig:
    try:
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigLoadError(f"Invalid TOML in {config_path}: {e}") from e
    except OSError as e:
        raise ConfigLoadError(f"Cannot read {config_path}: {e}") from e

    all_issue_code_values = {item.value for item in IssueCode}
    guides: dict[str, CustomGuideConfig] = {}
    for key, value in data.items():
        if key not in all_issue_code_values:
            raise ConfigLoadError(
                f"Unknown issue code '{key}' in {config_path}. " f"Use --list-issue-codes to see valid codes."
            )
        if not isinstance(value, dict):
            raise ConfigLoadError(f"Expected a table for '{key}' in {config_path}, got {type(value).__name__}")
        if "mode" in value:
            value = {**value, "mode": value["mode"].lower()}
        try:
            guides[key] = CustomGuideConfig.model_validate(value)
        except ValidationError as e:
            raise ConfigLoadError(f"Invalid guide configuration for '{key}' in {config_path}: {e}") from e

    return CustomGuidesConfig(guides=guides)


def load_custom_guides_config(repo_path: Path | None = None) -> CustomGuidesConfig:
    merged_guides: dict[str, CustomGuideConfig] = {}

    for config_path in get_guides_config_file_paths(repo_path):
        if config_path.exists():
            config = _load_single_guides_file(config_path)
            merged_guides.update(config.guides)

    return CustomGuidesConfig(guides=merged_guides)
