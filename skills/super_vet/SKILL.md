---
name: super_vet
description: Use super_vet when you want a higher-confidence review by running multiple vet instances in parallel across different modes and aggregating results as a union.
---

# Super Vet

**Use super_vet when you want a higher-confidence review by running multiple vet instances in parallel across different modes (agentic-claude, agentic-codex, and standard) and aggregating results as a union.**

Super vet is a wrapper around vet that launches N instances of each mode concurrently. It is useful when you want diverse analysis perspectives -- different modes and models catch different issues. The output is a union of all issues with source tracking (which run found each issue).

## Prerequisites

- `vet` must be installed and on PATH (see the vet skill for installation instructions)
- For agentic-claude runs: the `claude` CLI must be installed
- For agentic-codex runs: the `codex` CLI must be installed
- Standard runs only require API keys configured for vet

If a harness CLI is not available, set its run count to 0.

## Running Super Vet

Before running super_vet, determine the correct Python binary:
```bash
$(command -v python3 || command -v python)
```

### Basic Usage

Run 1 instance of each mode (agentic-claude, agentic-codex, standard):

```bash
python3 <skill_base>/scripts/super_vet.py "goal description"
```

### Specify Runs Per Mode

Run 2 of each mode:

```bash
python3 <skill_base>/scripts/super_vet.py "goal description" --runs 2
```

### Customize Per Mode

Run 2 agentic-claude, 1 agentic-codex, 3 standard:

```bash
python3 <skill_base>/scripts/super_vet.py "goal description" \
  --claude-runs 2 \
  --codex-runs 1 \
  --standard-runs 3
```

### Skip Unavailable Modes

If codex is not installed, set its count to 0:

```bash
python3 <skill_base>/scripts/super_vet.py "goal description" \
  --codex-runs 0
```

### Specify Models

Use different models for different modes:

```bash
python3 <skill_base>/scripts/super_vet.py "goal description" \
  --claude-model claude-opus-4-6 \
  --standard-model gpt-5 \
  --codex-runs 0
```

Or set a single model for all modes:

```bash
python3 <skill_base>/scripts/super_vet.py "goal description" --model claude-opus-4-6
```

### With Conversation History

Pass through vet's `--history-loader` option:

**OpenCode:**
```bash
python3 <skill_base>/scripts/super_vet.py "goal" \
  --history-loader "python3 <vet_skill_base>/scripts/export_opencode_session.py --session-id <ses_ID>"
```

**Claude Code:**
```bash
python3 <skill_base>/scripts/super_vet.py "goal" \
  --history-loader "python3 <vet_skill_base>/scripts/export_claude_code_session.py --session-file <path>"
```

**Codex:**
```bash
python3 <skill_base>/scripts/super_vet.py "goal" \
  --history-loader "python3 <vet_skill_base>/scripts/export_codex_session.py --session-file <path>"
```

### All Options

```
positional arguments:
  goal                    Goal description for vet

run configuration:
  --runs, -n N            Number of runs for EACH mode (default: 1)
  --claude-runs N         Number of agentic-claude runs
  --codex-runs N          Number of agentic-codex runs
  --standard-runs N       Number of standard (non-agentic) runs

model configuration:
  --model, -m MODEL       Model for all modes
  --claude-model MODEL    Model for agentic-claude runs
  --codex-model MODEL     Model for agentic-codex runs
  --standard-model MODEL  Model for standard runs

vet options (passed through):
  --base-commit REF       Git ref for diff base
  --history-loader CMD    Shell command to load conversation history
  --confidence-threshold N  Minimum confidence threshold (default: 0.0)
  --repo, -r PATH         Path to the repository

parallelism:
  --max-parallel N        Max concurrent vet processes (default: 6)
```

## Output Format

Super vet outputs JSON to stdout with the following structure:

```json
{
  "issues": [
    {
      "issue_code": "logic_error",
      "confidence": 0.95,
      "file_path": "src/auth.py",
      "line_number": 42,
      "description": "...",
      "severity": 4.0,
      "found_by": [
        {"mode": "agentic-claude", "model": "claude-opus-4-6", "run_index": 0, "label": "agentic-claude/claude-opus-4-6#0"},
        {"mode": "standard", "model": "claude-opus-4-6", "run_index": 0, "label": "standard/claude-opus-4-6#0"}
      ],
      "found_by_count": 2
    }
  ],
  "runs": [
    {"label": "agentic-claude/claude-opus-4-6#0", "mode": "agentic-claude", "model": "claude-opus-4-6", "run_index": 0, "issues_found": 3, "duration_seconds": 45.2, "returncode": 10, "error": null}
  ],
  "summary": {
    "total_unique_issues": 7,
    "total_runs": 6,
    "successful_runs": 6,
    "failed_runs": 0,
    "issues_by_mode": {"agentic-claude": 4, "agentic-codex": 3, "standard": 5}
  },
  "wall_time_seconds": 48.3
}
```

Issues are sorted by `found_by_count` (descending), then by `confidence` (descending). Issues found by more runs are more likely to be real issues.

Status messages are printed to stderr. Only the final JSON is printed to stdout.

## Interpreting Results

- **`found_by_count`**: Issues found by multiple independent runs across different modes are higher signal. An issue found by 3+ runs is very likely real.
- **`found_by`**: Shows which specific run(s) surfaced this issue. Useful for understanding which mode/model is most effective for your codebase.
- **Failed runs**: Check `runs[].error` for any failures. Agentic runs may fail if the harness CLI is not installed or API keys are missing.
- **Union semantics**: The output is the union of all issues. Some may be low-quality or duplicates that differ slightly in description. The agent should evaluate each issue before acting on it.

## When to Use Super Vet vs Regular Vet

- **Regular vet**: Fast, single-pass review. Good for frequent checks during development.
- **Super vet**: Thorough multi-perspective review. Use for important changes, PRs, or when you want high confidence that no issues were missed. Costs more and takes longer.
