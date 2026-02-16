from __future__ import annotations

# The choice to use argparse was primarily driven by the idea that vet will be called by agents / llms.
# Given this, we want to have the most standardized outputs possible.
import argparse
import json
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

from loguru import logger

from vet.api import find_issues
from vet.cli.config.cli_config_schema import CLI_DEFAULTS
from vet.cli.config.cli_config_schema import CliConfigPreset
from vet.cli.config.loader import ConfigLoadError
from vet.cli.config.loader import build_language_model_config
from vet.cli.config.loader import get_cli_config_file_paths
from vet.cli.config.loader import get_config_preset
from vet.cli.config.loader import get_max_output_tokens_for_model
from vet.cli.config.loader import load_cli_config
from vet.cli.config.loader import load_custom_guides_config
from vet.cli.config.loader import load_models_config
from vet.cli.config.loader import validate_api_key_for_model
from vet.cli.config.schema import ModelsConfig
from vet.cli.models import DEFAULT_MODEL_ID
from vet.cli.models import get_models_by_provider
from vet.cli.models import validate_model_id
from vet.formatters import OUTPUT_FIELDS
from vet.formatters import OUTPUT_FORMATS
from vet.formatters import format_github_review
from vet.formatters import format_issue_text
from vet.formatters import issue_to_dict
from vet.formatters import validate_output_fields
from vet.imbue_core.agents.llm_apis.errors import BadAPIRequestError
from vet.imbue_core.agents.llm_apis.errors import PromptTooLongError
from vet.imbue_core.data_types import AgentHarnessType
from vet.imbue_core.data_types import IssueCode
from vet.imbue_core.data_types import get_valid_issue_code_values
from vet.imbue_tools.get_conversation_history.get_conversation_history import parse_conversation_history
from vet.imbue_tools.types.vet_config import VetConfig

VERSION = version("verify-everything")

_ISSUE_CODE_FIELDS = frozenset({"enabled_issue_codes", "disabled_issue_codes"})
_PATH_FIELDS = frozenset({"repo", "output"})
_PATH_LIST_FIELDS = frozenset({"extra_context"})


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vet",
        description="Identify issues in code changes using LLM-based analysis.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "goal",
        type=str,
        nargs="?",
        default=CLI_DEFAULTS.goal,
        metavar="GOAL",
        help=(
            "Description of what the code change is trying to accomplish. "
            + "If not provided, only goal-independent issue identifiers will run."
        ),
    )

    parser.add_argument(
        "--repo",
        "-r",
        type=Path,
        default=Path.cwd(),
        metavar="PATH",
        help="Path to the repository for analysis (default: current directory)",
    )

    parser.add_argument(
        "--version",
        "-V",
        action="version",
        version=f"%(prog)s {VERSION}",
    )

    parser.add_argument(
        "--config",
        "-c",
        type=str,
        default=None,
        metavar="NAME",
        help="Name of the configuration to use. Configurations are defined in .vet/configs.toml in your target project's root or ~/.config/vet/configs.toml.",
    )
    parser.add_argument(
        "--list-configs",
        action="store_true",
        help="List all available named configurations",
    )

    diff_group = parser.add_argument_group("diff options")
    diff_group.add_argument(
        "--base-commit",
        type=str,
        default=CLI_DEFAULTS.base_commit,
        metavar="REF",
        help=f"Git commit, branch, or ref to use as the base for computing the diff (default: {CLI_DEFAULTS.base_commit})",
    )

    context_group = parser.add_argument_group("context options")
    context_group.add_argument(
        "--history-loader",
        type=str,
        default=CLI_DEFAULTS.history_loader,
        metavar="COMMAND",
        help=(
            "Shell command that outputs conversation history as JSON to stdout. "
            + "Used to derive a goal if one is not provided."
        ),
    )
    context_group.add_argument(
        "--extra-context",
        type=Path,
        nargs="*",
        default=CLI_DEFAULTS.extra_context,
        metavar="FILE",
        help="Path(s) to file(s) containing additional context (e.g., library documentation). Content is included in the prompt after the codebase snapshot.",
    )

    analysis_group = parser.add_argument_group("analysis options")
    # Valid issue codes are defined in imbue_core.data_types.IssueCode
    analysis_group.add_argument(
        "--enabled-issue-codes",
        type=IssueCode,
        nargs="+",
        default=CLI_DEFAULTS.enabled_issue_codes,
        metavar="CODE",
        help="Only report issues of the given type(s). Use --list-issue-codes to see valid codes.",
    )
    analysis_group.add_argument(
        "--disabled-issue-codes",
        type=IssueCode,
        nargs="+",
        default=CLI_DEFAULTS.disabled_issue_codes,
        metavar="CODE",
        help="Do not report issues of the given type(s). Use --list-issue-codes to see valid codes.",
    )
    analysis_group.add_argument(
        "--list-issue-codes",
        action="store_true",
        help="List all available issue codes",
    )

    model_group = parser.add_argument_group("model configuration")
    model_group.add_argument(
        "--model",
        "-m",
        type=str,
        default=CLI_DEFAULTS.model,
        metavar="MODEL",
        help=f"LLM to use for analysis (default: {DEFAULT_MODEL_ID}). ",
    )
    model_group.add_argument(
        "--list-models",
        action="store_true",
        help="List all available models",
    )
    model_group.add_argument(
        "--temperature",
        type=float,
        default=CLI_DEFAULTS.temperature,
        metavar="TEMP",
        help=f"Override the default temperature for the model (default: {CLI_DEFAULTS.temperature}).",
    )

    filter_group = parser.add_argument_group("filtering options")
    filter_group.add_argument(
        "--confidence-threshold",
        type=float,
        default=CLI_DEFAULTS.confidence_threshold,
        metavar="THRESHOLD",
        help=f"Minimum confidence score (0.0-1.0) for issues to be reported (default: {CLI_DEFAULTS.confidence_threshold})",
    )

    parallel_group = parser.add_argument_group("parallelization options")
    parallel_group.add_argument(
        "--max-workers",
        type=int,
        default=CLI_DEFAULTS.max_workers,
        metavar="N",
        help=f"Maximum number of parallel workers for identification (default: {CLI_DEFAULTS.max_workers})",
    )
    parallel_group.add_argument(
        "--max-spend",
        type=float,
        default=CLI_DEFAULTS.max_spend,
        metavar="DOLLARS",
        help="Maximum dollars to spend on API calls (default: no limit)",
    )

    output_group = parser.add_argument_group("output options")
    output_group.add_argument(
        "--output",
        "-o",
        type=Path,
        default=CLI_DEFAULTS.output,
        metavar="FILE",
        help="Output file path (default: stdout). Use - to write to stdout.",
    )
    output_group.add_argument(
        "--output-format",
        type=str,
        choices=OUTPUT_FORMATS,
        default=CLI_DEFAULTS.output_format,
        metavar="FORMAT",
        help=f"Output format. Choices: {', '.join(OUTPUT_FORMATS)} (default: {CLI_DEFAULTS.output_format})",
    )
    output_group.add_argument(
        "--output-fields",
        type=str,
        nargs="+",
        default=CLI_DEFAULTS.output_fields,
        metavar="FIELD",
        help="Output fields to include (default: all)",
    )
    output_group.add_argument(
        "--list-fields",
        action="store_true",
        help="List all available output data fields",
    )
    output_group.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=CLI_DEFAULTS.verbose,
        help="Show verbose logger messages",
    )
    output_group.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        default=CLI_DEFAULTS.quiet,
        help="Suppress progress indicator and non-essential output",
    )

    parser.add_argument(
        "--agentic",
        action="store_true",
        default=False,
        help=argparse.SUPPRESS,
    )

    parser.add_argument(
        "--agent-harness",
        type=AgentHarnessType,
        choices=list(AgentHarnessType),
        default=CLI_DEFAULTS.agent_harness,
        help=argparse.SUPPRESS,
    )

    return parser


# TODO: There are logical groupings of codes we should consider because some issue_codes are associated with the same prompts / categories of issues.
# This should likely be used to dictate the ordering instead of sorting.
def list_issue_codes() -> None:
    print("Available issue codes:")
    print()
    for code in sorted(get_valid_issue_code_values()):
        print(f"  {code}")


def list_models(user_config: ModelsConfig | None = None) -> None:
    print("Available models:")
    print()
    models_by_provider = get_models_by_provider(user_config)
    for provider, model_ids in sorted(models_by_provider.items()):
        print(f"  {provider}:")
        for model_id in sorted(model_ids):
            default_marker = " (default)" if model_id == DEFAULT_MODEL_ID else ""
            print(f"    {model_id}{default_marker}")


def list_fields() -> None:
    print("Available output fields:")
    print()
    for field in OUTPUT_FIELDS:
        print(f"  {field}")


def list_configs(cli_configs: dict[str, CliConfigPreset], repo_path: Path) -> None:
    print("Available configurations:")
    print()

    if not cli_configs:
        print("  No configurations found.")
        print()
        print("Configuration files are loaded from:")
        for path in get_cli_config_file_paths(repo_path):
            exists_marker = " (exists)" if path.exists() else ""
            print(f"  {path}{exists_marker}")
        return

    for name, preset in sorted(cli_configs.items()):
        print(f"  {name}:")
        preset_dict = preset.model_dump(exclude_none=True)
        if preset_dict:
            for key, value in preset_dict.items():
                print(f"    {key}: {value}")
        else:
            print("    (uses all defaults)")
        print()


def configure_logging(verbose: bool, quiet: bool) -> None:
    logger.remove()
    if quiet:
        level = "WARNING"
    elif verbose:
        level = "DEBUG"
    else:
        level = "INFO"
    logger.add(sys.stderr, level=level)


def load_conversation_from_command(command: str, cwd: Path) -> tuple:
    logger.info("Running history loader command: {}", command)
    result = subprocess.run(command, shell=True, capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0:
        logger.warning(f"History loader command failed with exit code {result.returncode}: {result.stderr}")
        return ()
    if not result.stdout.strip():
        logger.info("History loader command returned empty output, no conversation history loaded")
        return ()
    messages = parse_conversation_history(result.stdout)
    logger.info(
        "Loaded {} conversation history messages from history loader command",
        len(messages),
    )
    return messages


def apply_config_preset(args: argparse.Namespace, preset: CliConfigPreset) -> argparse.Namespace:
    preset_dict = preset.model_dump(exclude_none=True)

    for field, preset_value in preset_dict.items():
        default_value = getattr(CLI_DEFAULTS, field, None)
        if getattr(args, field) == default_value:
            if field in _ISSUE_CODE_FIELDS:
                preset_value = [IssueCode(code) for code in preset_value]
            elif field in _PATH_LIST_FIELDS:
                preset_value = [Path(p) for p in preset_value]
            elif field in _PATH_FIELDS:
                preset_value = Path(preset_value)
            setattr(args, field, preset_value)

    return args


# TODO: This string matching is brittle. Ideally each provider's exception manager would raise PromptTooLongError directly.
_CONTEXT_OVERFLOW_PATTERNS = [
    "prompt is too long",
    "context length exceeded",
    "context_length_exceeded",
    "maximum context length",
    "too many tokens",
    "reduce the length of the messages",
]


def _is_context_overflow(e: PromptTooLongError | BadAPIRequestError) -> bool:
    if isinstance(e, PromptTooLongError):
        return True
    error_msg = e.error_message.lower()
    return any(pattern in error_msg for pattern in _CONTEXT_OVERFLOW_PATTERNS)


def main(argv: list[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)

    goal = args.goal or ""

    repo_path = args.repo

    try:
        user_config = load_models_config(repo_path)
    except ConfigLoadError as e:
        print(f"Error loading model configuration: {e}", file=sys.stderr)
        return 2

    try:
        custom_guides_config = load_custom_guides_config(repo_path)
    except ConfigLoadError as e:
        print(f"Error loading custom guides: {e}", file=sys.stderr)
        return 2

    if args.list_issue_codes:
        list_issue_codes()
        return 0

    if args.list_models:
        list_models(user_config)
        return 0

    if args.list_fields:
        list_fields()
        return 0

    try:
        cli_configs = load_cli_config(repo_path)
    except ConfigLoadError as e:
        print(f"Error loading CLI configuration: {e}", file=sys.stderr)
        return 2

    if args.list_configs:
        list_configs(cli_configs, repo_path)
        return 0

    if args.config is not None:
        try:
            preset = get_config_preset(args.config, cli_configs, repo_path)
            args = apply_config_preset(args, preset)
        except ConfigLoadError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 2

    if not repo_path.exists():
        print(f"Error: Repository path does not exist: {repo_path}", file=sys.stderr)
        return 2

    if not repo_path.is_dir():
        print(f"Error: Repository path is not a directory: {repo_path}", file=sys.stderr)
        return 2

    if args.extra_context:
        for extra_context_file in args.extra_context:
            if not extra_context_file.exists():
                print(
                    f"Error: Extra context file does not exist: {extra_context_file}",
                    file=sys.stderr,
                )
                return 2

    if args.verbose and args.quiet:
        print(
            "Error: --verbose and --quiet are mutually exclusive",
            file=sys.stderr,
        )
        return 2

    if not 0.0 <= args.confidence_threshold <= 1.0:
        print(
            f"Error: Confidence threshold must be between 0.0 and 1.0, got: {args.confidence_threshold}",
            file=sys.stderr,
        )
        return 2

    if not 0.0 <= args.temperature <= 2.0:
        print(
            f"Error: Temperature must be between 0.0 and 2.0, got: {args.temperature}",
            file=sys.stderr,
        )
        return 2

    if args.max_spend is not None and args.max_spend <= 0:
        print(
            f"Error: Max spend must be a positive number, got: {args.max_spend}",
            file=sys.stderr,
        )
        return 2

    configure_logging(args.verbose, args.quiet)

    conversation_history = None
    if args.history_loader is not None:
        conversation_history = load_conversation_from_command(args.history_loader, repo_path)
    else:
        logger.info("No history loader provided, skipping conversation history loading")
    extra_context = None
    if args.extra_context:
        extra_context_parts = []
        for context_file in args.extra_context:
            extra_context_parts.append(context_file.read_text())
        extra_context = "\n\n".join(extra_context_parts)

    if args.output_fields is not None:
        try:
            validate_output_fields(args.output_fields)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 2

    model_id = args.model or DEFAULT_MODEL_ID

    try:
        model_id = validate_model_id(model_id, user_config)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    try:
        validate_api_key_for_model(model_id, user_config)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    # TODO: Support OFFLINE, UPDATE_SNAPSHOT, and MOCKED modes.
    language_model_config = build_language_model_config(model_id, user_config)
    max_output_tokens = get_max_output_tokens_for_model(model_id, user_config)

    disabled_identifiers = None if args.agentic else ("agentic_issue_identifier",)

    config = VetConfig(
        disabled_identifiers=disabled_identifiers,
        language_model_generation_config=language_model_config,
        enabled_issue_codes=(tuple(args.enabled_issue_codes) if args.enabled_issue_codes else None),
        disabled_issue_codes=(tuple(args.disabled_issue_codes) if args.disabled_issue_codes else None),
        temperature=args.temperature,
        filter_issues_below_confidence=args.confidence_threshold,
        max_identify_workers=args.max_workers,
        max_output_tokens=max_output_tokens or 20000,
        max_identifier_spend_dollars=args.max_spend,
        custom_guides_config=custom_guides_config,
        agent_harness_type=args.agent_harness,
    )

    try:
        issues = find_issues(
            repo_path=repo_path,
            relative_to=args.base_commit,
            goal=goal,
            config=config,
            conversation_history=conversation_history,
            extra_context=extra_context,
        )
    # TODO: This should be refactored so we only need to handle prompt too long errors when context is overfilled.
    except (PromptTooLongError, BadAPIRequestError) as e:
        if _is_context_overflow(e):
            print(
                "Error: The review failed because too much context was provided to the model. "
                "Consider using a model with a larger context window.",
                file=sys.stderr,
            )
            return 2
        if isinstance(e, BadAPIRequestError):
            print(f"Error: {e.error_message}", file=sys.stderr)
            return 1
        raise

    output_fields = args.output_fields if args.output_fields else OUTPUT_FIELDS

    output_file = None
    if args.output is not None and str(args.output) != "-":
        output_file = open(args.output, "w")
        output_stream = output_file
    else:
        output_stream = sys.stdout

    try:
        if not issues:
            if args.output_format == "json":
                print(json.dumps({"issues": []}, indent=2), file=output_stream)
            elif args.output_format == "github":
                payload = format_github_review(issues, output_fields)
                print(json.dumps(payload, indent=2), file=output_stream)
            elif not args.quiet:
                print("No issues found.", file=output_stream)
            return 0

        if args.output_format == "json":
            issues_list = [issue_to_dict(issue, output_fields) for issue in issues]
            print(json.dumps({"issues": issues_list}, indent=2), file=output_stream)
        elif args.output_format == "github":
            payload = format_github_review(issues, output_fields)
            print(json.dumps(payload, indent=2), file=output_stream)
        else:
            for issue in issues:
                print(format_issue_text(issue, output_fields), file=output_stream)
                print(file=output_stream)

        return 10
    finally:
        if output_file is not None:
            output_file.close()


if __name__ == "__main__":
    sys.exit(main())
