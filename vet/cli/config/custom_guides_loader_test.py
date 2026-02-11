from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from vet.cli.config.loader import ConfigLoadError
from vet.cli.config.loader import _load_single_guides_file
from vet.cli.config.loader import load_custom_guides_config
from vet.imbue_core.data_types import CustomGuideConfig


def _write_guides_toml(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def test_custom_guide_config_valid_fields() -> None:
    assert CustomGuideConfig(suffix="text").suffix == "text"
    assert CustomGuideConfig(prefix="text").prefix == "text"
    assert CustomGuideConfig(replace="text").replace == "text"

    both = CustomGuideConfig(prefix="before", suffix="after")
    assert both.prefix == "before"
    assert both.suffix == "after"


def test_custom_guide_config_replace_with_prefix_or_suffix_fails() -> None:
    with pytest.raises(ValidationError, match="replace"):
        CustomGuideConfig(replace="text", prefix="text")


def test_custom_guide_config_no_fields_fails() -> None:
    with pytest.raises(ValidationError, match="At least one"):
        CustomGuideConfig()


def test_custom_guide_config_extra_field_fails() -> None:
    with pytest.raises(ValidationError, match="extra"):
        CustomGuideConfig(mode="suffix", suffix="text")  # type: ignore[call-arg]


def test_load_single_guides_file_valid(tmp_path: Path) -> None:
    config_file = _write_guides_toml(
        tmp_path / "guides.toml",
        """
[logic_error]
suffix = "- Check for integer overflow"

[insecure_code]
replace = "- Check for SQL injection"
""",
    )

    result = _load_single_guides_file(config_file)

    assert "logic_error" in result.guides
    assert result.guides["logic_error"].suffix == "- Check for integer overflow"
    assert "insecure_code" in result.guides
    assert result.guides["insecure_code"].replace == "- Check for SQL injection"


def test_load_single_guides_file_unknown_issue_code(tmp_path: Path) -> None:
    config_file = _write_guides_toml(
        tmp_path / "guides.toml",
        """
[not_a_real_code]
suffix = "text"
""",
    )

    with pytest.raises(ConfigLoadError, match="Unknown issue code 'not_a_real_code'"):
        _load_single_guides_file(config_file)


def test_load_single_guides_file_invalid_toml(tmp_path: Path) -> None:
    config_file = _write_guides_toml(
        tmp_path / "guides.toml",
        "this is not [valid toml",
    )

    with pytest.raises(ConfigLoadError, match="Invalid TOML"):
        _load_single_guides_file(config_file)


def test_load_single_guides_file_invalid_schema(tmp_path: Path) -> None:
    config_file = _write_guides_toml(
        tmp_path / "guides.toml",
        """
[logic_error]
""",
    )

    with pytest.raises(ConfigLoadError, match="Invalid guide configuration"):
        _load_single_guides_file(config_file)


def test_load_custom_guides_no_files(tmp_path: Path) -> None:
    with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(tmp_path / "nonexistent")}):
        result = load_custom_guides_config(repo_path=tmp_path)
        assert result.guides == {}


def test_load_custom_guides_project_overrides_global(tmp_path: Path) -> None:
    xdg_config = tmp_path / "xdg"
    _write_guides_toml(
        xdg_config / "vet" / "guides.toml",
        """
[logic_error]
suffix = "- Global suffix"
""",
    )

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _write_guides_toml(
        repo_path / "guides.toml",
        """
[logic_error]
prefix = "- Project prefix"
""",
    )

    with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg_config)}):
        result = load_custom_guides_config(repo_path=repo_path)

    assert "logic_error" in result.guides
    guide = result.guides["logic_error"]
    assert guide.prefix == "- Project prefix"
    assert guide.suffix is None


def test_load_custom_guides_different_codes_merged(tmp_path: Path) -> None:
    xdg_config = tmp_path / "xdg"
    _write_guides_toml(
        xdg_config / "vet" / "guides.toml",
        """
[logic_error]
suffix = "- Global logic error suffix"
""",
    )

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _write_guides_toml(
        repo_path / "guides.toml",
        """
[insecure_code]
replace = "- Project insecure code replacement"
""",
    )

    with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg_config)}):
        result = load_custom_guides_config(repo_path=repo_path)

    assert "logic_error" in result.guides
    assert "insecure_code" in result.guides
    assert result.guides["logic_error"].suffix == "- Global logic error suffix"
    assert result.guides["insecure_code"].replace == "- Project insecure code replacement"
