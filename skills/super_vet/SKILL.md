---
name: super_vet
description: Use super_vet when you want a higher-confidence review by running multiple vet instances in parallel across different modes and aggregating results as a union.
---

# Super Vet

**Use super_vet when you want a higher-confidence review by running multiple vet instances in parallel across different modes (agentic-claude, agentic-codex, and standard) and aggregating results as a union.**

Super vet is a wrapper around vet that launches N instances of each mode concurrently. It is useful when you want diverse analysis perspectives. The output is a union of all issues with source tracking.

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
  --base-commit REF       Git ref for diff base (in general, run against main)
  --history-loader CMD    Shell command to load conversation history
  --confidence-threshold N  Minimum confidence threshold (default: 0.0)
  --repo, -r PATH         Path to the repository

parallelism:
  --max-parallel N        Max concurrent vet processes (default: 6)
```

## Interpreting Results

- **`found_by_count`**: Issues found by multiple independent runs across different modes are higher signal. An issue found by 3+ runs is very likely real.
- **`found_by`**: Shows which specific run(s) surfaced this issue. Useful for understanding which mode/model is most effective for your codebase.
- **Failed runs**: Check `runs[].error` for any failures. Agentic runs may fail if the harness CLI is not installed or API keys are missing.
- **Union semantics**: The output is the union of all issues. Some may be low-quality or duplicates that differ slightly in description. The agent should evaluate each issue before acting on it.

## When to Use Super Vet vs Regular Vet

- **Regular vet**: Fast, single-pass review. Good for frequent checks during development.
- **Super vet**: Thorough multi-perspective review. Use for important changes, PRs, or when you want high confidence that no issues were missed. Costs more and takes longer.
