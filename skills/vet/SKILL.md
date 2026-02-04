---
name: vet
description: Run VET (Verify Everything) to check code changes for issues. Use after making code changes to catch problems that tests and linters miss.
---

# Vet

Vet reviews git diffs and conversation history to find issues in code changes.

## When to Use

- After completing code changes, before committing
- When asked to review or verify changes
- In CI pipelines to validate PRs

## Running Vet

### Basic Usage

```bash
vet "description of what the changes should accomplish" --base-commit main
```

### With Conversation History

To include the current conversation for better analysis, set the session environment variable and use `--history-loader`:

**OpenCode:**
```bash
export VET_SESSION_ID="<current-session-id>"
vet "goal" --history-loader "python /path/to/skills/vet/scripts/export_opencode_session.py"
```

**Codex:**
```bash
export CODEX_SESSION_FILE="<path-to-current-session.jsonl>"
vet "goal" --history-loader "python /path/to/skills/vet/scripts/export_codex_session.py"
```

### Finding Your Session

**OpenCode:** The session ID appears in task metadata or can be found as the most recent file in `~/.local/share/opencode/storage/session/`.

**Codex:** Session files are stored in `~/.codex/sessions/YYYY/MM/DD/`. Find the most recently modified `.jsonl` file.

## Common Options

- `--base-commit REF`: Git ref for diff base (default: HEAD)
- `--model MODEL`: LLM model to use (default: claude-4-5-haiku)
- `--confidence-threshold N`: Minimum confidence 0.0-1.0 (default: 0.8)
- `--output-format FORMAT`: Output as `text` or `json`
- `--quiet`: Suppress progress output

## Interpreting Results

Vet returns exit code 0 if no issues found, 1 if issues found, 2 for errors.

Each issue includes:
- **code**: Issue type (e.g., `logic_error`, `incomplete_integration`)
- **confidence**: How certain vet is (0.0-1.0)
- **description**: What the issue is
- **location**: File and line number if applicable

## Configuration

Create `vet.toml` in your repo for project-specific presets:

```toml
[ci]
confidence_threshold = 0.9
base_commit = "main"
quiet = true
```

Then run with `vet --config ci "goal"`.
