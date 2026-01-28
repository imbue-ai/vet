"""CLI configuration schema definitions.

This module defines two related but distinct models for CLI configuration:

1. CliDefaults: Holds the actual default values for CLI arguments (e.g., temperature=0.0).
   This is the single source of truth for what values are used when no override is provided.

2. CliConfigPreset: Used for config file presets where all fields default to None.
   The None sentinel means "not specified in this preset" - allowing presets to override
   only specific fields while leaving others at their defaults.

These models intentionally have the same field names but different default values.
A test in cli_config_test.py verifies field parity to catch drift.
"""

from __future__ import annotations

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class CliConfigPreset(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    goal: str | None = None
    repo: str | None = None
    base_commit: str | None = None
    history_loader: str | None = None
    extra_context: list[str] | None = None
    enabled_issue_codes: list[str] | None = None
    disabled_issue_codes: list[str] | None = None
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    max_workers: int | None = Field(default=None, ge=1)
    output: str | None = None
    output_format: str | None = None
    output_fields: list[str] | None = None
    verbose: bool | None = None
    quiet: bool | None = None


class CliDefaults(BaseModel):
    """Actual default values for CLI arguments. See module docstring for design rationale."""

    model_config = ConfigDict(frozen=True)

    goal: str | None = None
    repo: str | None = None
    base_commit: str = "HEAD"
    history_loader: str | None = None
    extra_context: list[str] | None = None
    enabled_issue_codes: list[str] | None = None
    disabled_issue_codes: list[str] | None = None
    model: str | None = None
    temperature: float = 0.0
    confidence_threshold: float = 0.8
    max_workers: int = 2
    output: str | None = None
    output_format: str = "text"
    output_fields: list[str] | None = None
    verbose: bool = False
    quiet: bool = False


CLI_DEFAULTS = CliDefaults()


def parse_cli_config_from_dict(data: dict) -> dict[str, CliConfigPreset]:
    configs: dict[str, CliConfigPreset] = {}
    for name, preset_data in data.items():
        if isinstance(preset_data, dict):
            configs[name] = CliConfigPreset.model_validate(preset_data)
    return configs


def merge_presets(base: CliConfigPreset, override: CliConfigPreset) -> CliConfigPreset:
    base_dict = base.model_dump()
    override_dict = override.model_dump()
    merged = {k: override_dict[k] if override_dict.get(k) is not None else base_dict[k] for k in base_dict}
    return CliConfigPreset.model_validate(merged)
