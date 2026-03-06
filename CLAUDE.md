# Vet

Vet (Verify Everything) is an LLM-based code review tool that checks git diffs and agent conversation history for issues. The package is published as `verify-everything` on PyPI; the CLI command is `vet`.

## Key Commands

- `uv run vet "goal"` — run vet on current repo changes
- `uv run pytest` — run all unit tests (the only supported test runner; do not use alternatives)
- `uvx pre-commit run --all-files` — run black + isort across the repo

See [DEVELOPMENT.md](DEVELOPMENT.md) for containerized dev setup, logging conventions, CI/CD, and release steps.

## Key Files

| File | Purpose |
|---|---|
| `vet/api.py` | Public `find_issues()` entry point; also contains goal auto-generation logic |
| `vet/cli/main.py` | CLI argument parsing, config loading, logging setup |
| `vet/issue_identifiers/registry.py` | Orchestrates the 4-stage identification pipeline |
| `vet/issue_identifiers/harnesses/` | The three harness implementations (single_prompt, conversation_single_prompt, agentic) |
| `vet/imbue_tools/repo_utils/project_context.py` | `LazyProjectContext` — context window budget management |
| `vet/imbue_tools/types/vet_config.py` | `VetConfig` — the main configuration object |
| `vet/imbue_core/data_types.py` | Core enums and data classes (`IssueCode`, `IssueIdentifierType`, etc.) |
| `vet/issue_identifiers/identification_guides.py` | Per-issue-code prompting guides; default issue code groupings |
| `.vet/configs.toml` | Named configuration profiles for this repo (ci, security, high-precision) |
| `.vet/models.json` | Custom model definitions for this repo |

## Non-Obvious Behaviors

**See [ARCHITECTURE.md](ARCHITECTURE.md) for full details.** Brief summary:

- **4-stage pipeline**: identification → collation → filtration → deduplication. Not all stages run in every invocation; each is toggled by `VetConfig` flags.
- **3 harness types**: `SinglePromptHarness` (diff+goal → one LLM call), `ConversationSinglePromptHarness` (adds conversation history), `AgenticHarness` (routes through Claude Code / Codex CLI). Multiple identifier types that share a harness are **merged into one LLM call**.
- **Goal auto-generation**: if `--goal` is omitted but conversation history is provided (via `--history-loader`), an LLM call synthesizes a goal before identification begins.
- **LazyProjectContext**: reserves token budget for prompt + diff + output before loading project files on demand; prevents context overflow silently.
- **Silent skipping**: identifiers whose required inputs are absent (e.g., `CONVERSATION_HISTORY_IDENTIFIER` when no history is provided) are skipped with a DEBUG log — not an error.

## Logging

New entry points must call `configure_logging(verbose, log_file)` from `vet.cli.main`. User-facing status goes to `print(..., file=sys.stderr)`; loguru is for internal diagnostics only. See `DEVELOPMENT.md` for log level conventions.
