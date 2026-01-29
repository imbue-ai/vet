from __future__ import annotations

import argparse
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from vet.cli.config.cli_config_schema import CLI_DEFAULTS
from vet.cli.config.cli_config_schema import CliConfigPreset
from vet.cli.config.cli_config_schema import merge_presets
from vet.cli.config.cli_config_schema import parse_cli_config_from_dict
from vet.cli.config.loader import ConfigLoadError
from vet.cli.config.loader import _load_cli_config_file
from vet.cli.config.loader import get_cli_config_file_paths
from vet.cli.config.loader import get_config_preset
from vet.cli.config.loader import load_cli_config
from vet.cli.main import apply_config_preset


def test_parse_cli_config_from_dict_parses_single_config() -> None:
    data = {
        "ci": {
            "confidence_threshold": 0.9,
            "max_workers": 4,
            "quiet": True,
        }
    }

    result = parse_cli_config_from_dict(data)

    assert "ci" in result
    assert result["ci"].confidence_threshold == 0.9
    assert result["ci"].max_workers == 4
    assert result["ci"].quiet is True


def test_parse_cli_config_from_dict_parses_multiple_configs() -> None:
    data = {
        "ci": {"confidence_threshold": 0.9},
        "strict": {"confidence_threshold": 0.6, "model": "claude-4-sonnet"},
        "default": {},
    }

    result = parse_cli_config_from_dict(data)

    assert len(result) == 3
    assert result["ci"].confidence_threshold == 0.9
    assert result["strict"].confidence_threshold == 0.6
    assert result["strict"].model == "claude-4-sonnet"
    assert result["default"].confidence_threshold is None


def test_parse_cli_config_from_dict_handles_all_fields() -> None:
    data = {
        "full": {
            "goal": "Check for security issues",
            "repo": "/path/to/repo",
            "base_commit": "main",
            "history_loader": "cat history.jsonl",
            "extra_context": ["context1.txt", "context2.txt"],
            "enabled_issue_codes": ["correctness", "style"],
            "disabled_issue_codes": ["minor"],
            "model": "test-model",
            "temperature": 0.7,
            "confidence_threshold": 0.85,
            "max_workers": 8,
            "output": "results.json",
            "output_format": "json",
            "output_fields": ["file", "line", "message"],
            "verbose": True,
            "quiet": False,
        }
    }

    result = parse_cli_config_from_dict(data)

    preset = result["full"]
    assert preset.goal == "Check for security issues"
    assert preset.repo == "/path/to/repo"
    assert preset.base_commit == "main"
    assert preset.history_loader == "cat history.jsonl"
    assert preset.extra_context == ["context1.txt", "context2.txt"]
    assert preset.enabled_issue_codes == ["correctness", "style"]
    assert preset.disabled_issue_codes == ["minor"]
    assert preset.model == "test-model"
    assert preset.temperature == 0.7
    assert preset.confidence_threshold == 0.85
    assert preset.max_workers == 8
    assert preset.output == "results.json"
    assert preset.output_format == "json"
    assert preset.output_fields == ["file", "line", "message"]
    assert preset.verbose is True
    assert preset.quiet is False


def test_merge_presets_override_takes_precedence() -> None:
    base = CliConfigPreset(confidence_threshold=0.8, max_workers=2, model="base-model")
    override = CliConfigPreset(confidence_threshold=0.9, max_workers=None, model="override-model")

    result = merge_presets(base, override)

    assert result.confidence_threshold == 0.9
    assert result.max_workers == 2
    assert result.model == "override-model"


def test_merge_presets_preserves_base_when_override_is_none() -> None:
    base = CliConfigPreset(
        confidence_threshold=0.8,
        max_workers=4,
        model="base-model",
        verbose=True,
    )
    override = CliConfigPreset()

    result = merge_presets(base, override)

    assert result.confidence_threshold == 0.8
    assert result.max_workers == 4
    assert result.model == "base-model"
    assert result.verbose is True


def test_cli_defaults_and_cli_config_preset_have_same_fields() -> None:
    """Verify CliDefaults and CliConfigPreset define the same fields.

    These two models exist for different purposes:
    - CliDefaults: Holds actual default values for CLI arguments (e.g., temperature=0.0)
    - CliConfigPreset: Used for config file presets where None means "not specified"

    They must have identical field names to ensure presets can override any default.
    This test catches drift if a field is added to one model but not the other.
    """
    from vet.cli.config.cli_config_schema import CliDefaults

    defaults_fields = set(CliDefaults.model_fields.keys())
    preset_fields = set(CliConfigPreset.model_fields.keys())

    assert defaults_fields == preset_fields, (
        f"Field mismatch between CliDefaults and CliConfigPreset.\n"
        f"Only in CliDefaults: {defaults_fields - preset_fields}\n"
        f"Only in CliConfigPreset: {preset_fields - defaults_fields}"
    )


def test_get_cli_config_file_paths_returns_global_path(tmp_path: Path) -> None:
    with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(tmp_path)}):
        paths = get_cli_config_file_paths(repo_path=None)

    assert len(paths) == 1
    assert paths[0] == tmp_path / "vet" / "config.toml"


def test_get_cli_config_file_paths_includes_project_path(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
        paths = get_cli_config_file_paths(repo_path=repo_path)

    assert len(paths) == 2
    assert paths[0] == tmp_path / "xdg" / "vet" / "config.toml"
    assert paths[1] == repo_path / "vet.toml"


def test_get_cli_config_file_paths_finds_git_root(tmp_path: Path) -> None:
    git_root = tmp_path / "repo"
    git_root.mkdir()
    (git_root / ".git").mkdir()
    subdir = git_root / "src" / "deep"
    subdir.mkdir(parents=True)

    with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
        paths = get_cli_config_file_paths(repo_path=subdir)

    assert paths[1] == git_root / "vet.toml"


def test_load_cli_config_file_loads_valid_toml(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[ci]
confidence_threshold = 0.9
max_workers = 4
quiet = true

[strict]
confidence_threshold = 0.6
model = "claude-4-sonnet"
"""
    )

    result = _load_cli_config_file(config_file)

    assert "ci" in result
    assert result["ci"].confidence_threshold == 0.9
    assert result["ci"].max_workers == 4
    assert result["ci"].quiet is True
    assert "strict" in result
    assert result["strict"].model == "claude-4-sonnet"


def test_load_cli_config_file_raises_on_invalid_toml(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text("not = valid = toml")

    with pytest.raises(ConfigLoadError) as exc_info:
        _load_cli_config_file(config_file)

    assert "Invalid TOML" in str(exc_info.value)


def test_load_cli_config_file_raises_on_invalid_schema(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[ci]
confidence_threshold = "not-a-float"
"""
    )

    with pytest.raises(ConfigLoadError) as exc_info:
        _load_cli_config_file(config_file)

    assert "Invalid configuration" in str(exc_info.value)


def test_load_cli_config_file_raises_on_unknown_field(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[ci]
unknown_field = "value"
"""
    )

    with pytest.raises(ConfigLoadError) as exc_info:
        _load_cli_config_file(config_file)

    assert "Invalid configuration" in str(exc_info.value)


def test_load_cli_config_returns_empty_when_no_files_exist(tmp_path: Path) -> None:
    with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(tmp_path / "nonexistent")}):
        result = load_cli_config(repo_path=tmp_path)

    assert result == {}


def test_load_cli_config_loads_single_file(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    config_file = repo_path / "vet.toml"
    config_file.write_text(
        """
[ci]
confidence_threshold = 0.9
"""
    )

    with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(tmp_path / "nonexistent")}):
        result = load_cli_config(repo_path=repo_path)

    assert "ci" in result
    assert result["ci"].confidence_threshold == 0.9


def test_load_cli_config_merges_global_and_project(tmp_path: Path) -> None:
    xdg_config = tmp_path / "xdg"
    (xdg_config / "vet").mkdir(parents=True)
    global_config = xdg_config / "vet" / "config.toml"
    global_config.write_text(
        """
[ci]
confidence_threshold = 0.8
max_workers = 2

[global-only]
model = "global-model"
"""
    )

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    project_config = repo_path / "vet.toml"
    project_config.write_text(
        """
[ci]
confidence_threshold = 0.9

[project-only]
model = "project-model"
"""
    )

    with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg_config)}):
        result = load_cli_config(repo_path=repo_path)

    assert result["ci"].confidence_threshold == 0.9
    assert result["ci"].max_workers == 2

    assert "global-only" in result
    assert result["global-only"].model == "global-model"
    assert "project-only" in result
    assert result["project-only"].model == "project-model"


def test_get_config_preset_returns_preset() -> None:
    configs = {
        "ci": CliConfigPreset(confidence_threshold=0.9),
        "strict": CliConfigPreset(confidence_threshold=0.6),
    }

    result = get_config_preset("ci", configs)

    assert result.confidence_threshold == 0.9


def test_get_config_preset_raises_on_unknown_with_available() -> None:
    configs = {
        "ci": CliConfigPreset(),
        "strict": CliConfigPreset(),
    }

    with pytest.raises(ConfigLoadError) as exc_info:
        get_config_preset("unknown", configs)

    error_msg = str(exc_info.value)
    assert "unknown" in error_msg
    assert "ci" in error_msg
    assert "strict" in error_msg


def test_get_config_preset_raises_on_unknown_with_no_configs(tmp_path: Path) -> None:
    configs: dict[str, CliConfigPreset] = {}
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
        with pytest.raises(ConfigLoadError) as exc_info:
            get_config_preset("unknown", configs, repo_path)

    error_msg = str(exc_info.value)
    assert "unknown" in error_msg
    assert "No configuration files found" in error_msg
    # Verify the error message contains dynamically generated paths with labels
    assert f"{tmp_path / 'xdg' / 'vet' / 'config.toml'} (global)" in error_msg
    assert f"{repo_path / 'vet.toml'} (project)" in error_msg


def _create_default_args() -> argparse.Namespace:
    return argparse.Namespace(
        model=CLI_DEFAULTS.model,
        temperature=CLI_DEFAULTS.temperature,
        confidence_threshold=CLI_DEFAULTS.confidence_threshold,
        max_workers=CLI_DEFAULTS.max_workers,
        output_format=CLI_DEFAULTS.output_format,
        output_fields=CLI_DEFAULTS.output_fields,
        verbose=CLI_DEFAULTS.verbose,
        quiet=CLI_DEFAULTS.quiet,
        enabled_issue_codes=CLI_DEFAULTS.enabled_issue_codes,
        disabled_issue_codes=CLI_DEFAULTS.disabled_issue_codes,
    )


def test_apply_config_preset_applies_all_values() -> None:
    args = _create_default_args()
    preset = CliConfigPreset(
        model="preset-model",
        temperature=0.7,
        confidence_threshold=0.9,
        max_workers=4,
        output_format="json",
        output_fields=["file", "line"],
        verbose=True,
        quiet=False,
    )

    result = apply_config_preset(args, preset)

    assert result.model == "preset-model"
    assert result.temperature == 0.7
    assert result.confidence_threshold == 0.9
    assert result.max_workers == 4
    assert result.output_format == "json"
    assert result.output_fields == ["file", "line"]
    assert result.verbose is True


def test_apply_config_preset_cli_args_take_precedence() -> None:
    args = argparse.Namespace(
        model="cli-model",
        temperature=0.0,
        confidence_threshold=0.95,
        max_workers=2,
        output_format="text",
        output_fields=None,
        verbose=False,
        quiet=False,
        enabled_issue_codes=None,
        disabled_issue_codes=None,
    )
    preset = CliConfigPreset(
        model="preset-model",
        temperature=0.3,
        confidence_threshold=0.6,
        max_workers=8,
    )

    result = apply_config_preset(args, preset)

    assert result.model == "cli-model"
    assert result.confidence_threshold == 0.95

    assert result.temperature == 0.3
    assert result.max_workers == 8


def test_apply_config_preset_leaves_defaults_when_preset_is_none() -> None:
    args = _create_default_args()
    preset = CliConfigPreset()

    result = apply_config_preset(args, preset)

    assert result.model is None
    assert result.temperature == 0.0
    assert result.confidence_threshold == 0.8
    assert result.max_workers == 2


def test_apply_config_preset_handles_issue_codes() -> None:
    args = _create_default_args()
    preset = CliConfigPreset(
        enabled_issue_codes=["incorrect_function_implementation"],
        disabled_issue_codes=["bad_naming"],
    )

    result = apply_config_preset(args, preset)

    assert len(result.enabled_issue_codes) == 1
    assert result.enabled_issue_codes[0].value == "incorrect_function_implementation"
    assert len(result.disabled_issue_codes) == 1
    assert result.disabled_issue_codes[0].value == "bad_naming"
