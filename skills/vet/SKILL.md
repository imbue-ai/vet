---
name: vet
description: IMPORTANT - Run vet immediately after ANY code edit, file deletion, or refactor. Do not batch changes. Do not wait to be asked.
---

# Vet

**Run vet immediately after ANY code change. Do not batch. Do not wait to be asked.**

Vet reviews git diffs and conversation history to find issues in code changes. It is most effective when run frequently with conversation history, which helps it catch misunderstandings between what was requested and what was implemented.

## Installation

Install vet using pip or uv:

```bash
# Using pip
pip install git+https://github.com/imbue-ai/vet.git

# Using uv (recommended)
uv pip install git+https://github.com/imbue-ai/vet.git

# For development (from local clone)
cd /path/to/vet
pip install -e .
```

**Requirements:**
- Python 3.11 or higher
- Set `ANTHROPIC_API_KEY` environment variable (or configure another supported model provider)

Verify installation:
```bash
vet --help
```

## When to Run

Run vet after:
- Editing any file
- Deleting any file
- Refactoring code
- Completing a bugfix
- Adding a new feature or function

Do NOT wait until:
- The user asks you to
- You've made multiple changes
- You're about to commit

## Running Vet

### Standard Usage (Recommended)

Always include conversation history for best results. Set the session environment variable and use `--history-loader`:

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

### Without Conversation History (Not Recommended)

Running without history loses important context about intent and requirements. Only use this when history is genuinely unavailable:

```bash
vet "description of what the changes should accomplish" --base-commit main
```

**Warning:** Without conversation history, vet cannot detect mismatches between what was requested and what was implemented. It can only analyze the code changes in isolation.

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
