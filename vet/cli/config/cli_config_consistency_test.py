from __future__ import annotations

from vet.cli.config.cli_config_schema import CliConfigPreset
from vet.cli.config.cli_config_schema import CliDefaults
from vet.cli.main import create_parser

IGNORED_ARGS = {
    "help",
    "version",
    # CLI-only flags that select behavior rather than configure defaults
    "config",
    "list_configs",
    "list_models",
    "list_issue_codes",
    "list_fields",
    # agent-mode flags are intentionally CLI-only
    "agentic",
    "agent_harness",
    "update_models",
}


def _extract_cli_arg_dests() -> set[str]:
    parser = create_parser()
    return {action.dest for action in parser._actions if action.dest and action.dest not in IGNORED_ARGS}


def test_cli_args_present_in_cli_defaults_and_presets() -> None:
    """Ensure every CLI argument that is meant to be configurable
    appears in both `CliDefaults` and `CliConfigPreset`.
    """
    cli_args = _extract_cli_arg_dests()

    defaults_fields = set(CliDefaults.model_fields.keys())
    preset_fields = set(CliConfigPreset.model_fields.keys())

    missing_in_defaults = cli_args - defaults_fields
    missing_in_presets = cli_args - preset_fields

    assert not missing_in_defaults, f"CLI args missing from CliDefaults: {sorted(missing_in_defaults)}"
    assert not missing_in_presets, f"CLI args missing from CliConfigPreset: {sorted(missing_in_presets)}"
