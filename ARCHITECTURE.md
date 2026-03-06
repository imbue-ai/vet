# Vet — Internal Architecture

This document covers non-obvious internal behaviors not described in the [README](README.md) or [DEVELOPMENT.md](DEVELOPMENT.md).

## The 4-Stage Identification Pipeline

`vet/issue_identifiers/registry.py:run()` orchestrates all issue identification through four sequential stages. Not all stages run in every invocation — each can be toggled via `VetConfig`.

```
         IdentifierInputs + ProjectContext
                      │
          ┌───────────▼────────────┐
          │   1. Identification    │  Each identifier yields GeneratedIssueSchema objects
          └───────────┬────────────┘
                      │ (only AgenticHarness)
          ┌───────────▼────────────┐
          │    2. Collation        │  Agentic refinement of findings (config.enable_collation)
          └───────────┬────────────┘
                      │ (config.filter_issues)
          ┌───────────▼────────────┐
          │    3. Filtration       │  LLM re-evaluates each issue; low-confidence issues dropped
          └───────────┬────────────┘
                      │ (config.enable_deduplication)
          ┌───────────▼────────────┐
          │   4. Deduplication     │  Issues from all identifiers merged; duplicates removed
          └───────────┬────────────┘
                      │
               IssueIdentifierResult
```

### Stage details

**1. Identification** — each enabled identifier converts `IdentifierInputs` into its required input type and calls `identify_issues()`, which yields `GeneratedIssueSchema` objects (raw LLM-detected issues, not yet filtered).

**2. Collation** — runs only for identifiers where `requires_agentic_collation=True` (currently only `AgenticHarness`) AND `config.enable_collation` is `True`. An agent reviews and refines the raw findings before they proceed downstream. If collation requires inputs that are missing (e.g., no diff), the identifier is skipped entirely with a WARNING log.

**3. Filtration** — when `config.filter_issues=True`, a second LLM call re-evaluates each issue and drops ones below a confidence threshold. This is separate from the `--confidence-threshold` CLI option, which is a simpler scalar filter applied in `api.py` after the pipeline completes.

**4. Deduplication** — when `config.enable_deduplication=True`, equivalent issues that different identifiers both reported are collapsed into one. The deduplication is cross-identifier (not within a single identifier's output).

## Three Harness Types

A **harness** defines how an identifier sends inputs to an LLM. Each harness produces a concrete `IssueIdentifier` instance via `make_issue_identifier()`.

| Harness | Location | Input type | How it calls the LLM | Requires agentic collation |
|---|---|---|---|---|
| `SinglePromptHarness` | `harnesses/single_prompt.py` | `CommitInputs` (diff + goal) | One synchronous LLM API call | No |
| `ConversationSinglePromptHarness` | `harnesses/conversation_single_prompt.py` | `ConversationHistoryInputs` (diff + goal + conversation) | One synchronous LLM API call | No |
| `AgenticHarness` | `harnesses/agentic.py` | `CommitInputs` (diff + goal) | Spawns external agent CLI (Claude Code or Codex); agent has file-reading tools | **Yes** |

`SinglePromptHarness` and `ConversationSinglePromptHarness` use the same Jinja2 prompt template; the conversation harness adds the conversation history block.

`AgenticHarness` supports parallel sub-tasks per issue type when `config.enable_parallel_agentic_issue_identification=True`.

## Identifier Types and Harness Presets

`HARNESS_PRESETS` in `registry.py` is the **transitional design** that pairs each `IssueIdentifierType` with a harness and a default set of issue codes:

```python
HARNESS_PRESETS = [
    (IssueIdentifierType.AGENTIC_ISSUE_IDENTIFIER,        AgenticHarness,                   commit_codes + correctness_codes),
    (IssueIdentifierType.BATCHED_COMMIT_CHECK,            SinglePromptHarness,               commit_codes),
    (IssueIdentifierType.CONVERSATION_HISTORY_IDENTIFIER, ConversationSinglePromptHarness,   conversation_codes),
    (IssueIdentifierType.CORRECTNESS_COMMIT_CLASSIFIER,   SinglePromptHarness,               correctness_codes),
]
```

**Merging**: If multiple enabled identifier types share the same harness, `_build_identifiers()` merges them into **one** `IssueIdentifier` instance with the union of their issue codes. For example, enabling both `BATCHED_COMMIT_CHECK` and `CORRECTNESS_COMMIT_CLASSIFIER` produces a single `SinglePromptHarness` call that checks all issue codes in one prompt, rather than two separate LLM calls.

> **Transitional note**: `HARNESS_PRESETS` is explicitly labeled in the code as a transitional structure. The eventual goal is to let `VetConfig` enable/disable harnesses and issue codes independently, with the registry automatically pairing them. For now, the `--enable-identifiers` / `--disable-identifiers` CLI flags control which presets are active.

## Goal Auto-Generation

Source: `vet/api.py:36-47`

When `--goal` is not provided (or is empty), `get_issues_with_raw_responses()` follows this logic:

```
goal provided?
  ├─ Yes → use it as-is
  └─ No  →
       conversation history provided?
         ├─ Yes → call get_goal_from_conversation() [one LLM call] to synthesize a goal
         └─ No  → goal = "" (only goal-independent identifiers will run)
```

The goal synthesis uses the same `VetConfig.language_model_generation_config` as the main identification run. If goal generation fails (e.g., LLM error), a `ConversationLoadingError` is raised and propagated to the CLI.

This means: running `vet --history-loader "cmd"` without `--goal` is valid and intentional — vet will derive the goal from the conversation.

## Context Window Budget Management

Source: `vet/api.py:59-68`, `vet/imbue_tools/repo_utils/project_context.py`

Before loading any project files, `LazyProjectContext.build()` computes a token budget:

```
available_for_project_context = context_window
                                - VET_MAX_PROMPT_TOKENS   # prompt template overhead
                                - diff_no_binary_tokens   # the diff itself
                                - config.max_output_tokens # space for LLM response
```

Project source files are then loaded **on demand** (hence "Lazy"), filling the remaining budget. If the budget is exhausted, additional files are not loaded. This prevents context window overflow for large repos without requiring the user to configure anything.

`VET_MAX_PROMPT_TOKENS` is defined in `vet/repo_utils.py` and represents a conservative upper bound for the non-context portions of the prompt.

## IdentifierInputs: Optional Fields and Silent Skipping

Source: `vet/imbue_tools/get_conversation_history/input_data_types.py`, `registry.py:185-198`

`IdentifierInputs` stores all possible inputs with optional fields:

```python
@dataclass
class IdentifierInputs:
    maybe_diff: str | None
    maybe_goal: str | None
    maybe_conversation_history: tuple[...] | None
    maybe_extra_context: str | None
```

Each harness's identifier calls `identifier.to_required_inputs(identifier_inputs)`, which asserts that its required fields are non-None. If any required field is missing, `IdentifierInputsMissingError` is raised.

The registry catches this exception per-identifier and **silently skips** the identifier with a DEBUG-level log message (not an error or warning). The run continues with the remaining compatible identifiers.

Practical implications:

- `CONVERSATION_HISTORY_IDENTIFIER` is **always skipped** when no `--history-loader` is provided (no conversation history → missing required input).
- If no diff exists (no changes since `--base-commit`), all diff-requiring identifiers are skipped. `find_issues()` returns early with an empty tuple before even reaching the registry.
- `--goal` being absent does not cause skipping; goal auto-generation (see above) runs first.
