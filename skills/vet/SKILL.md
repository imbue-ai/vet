---
name: vet
description: Run vet immediately after ANY logical unit of code changes. Do not batch your changes, do not wait to be asked to run vet, make sure you are proactive.
---

# Vet

**Run vet immediately after ANY logical unit of code changes. Do not batch changes, do not wait to be asked to run vet, make sure you are proactive.**

Vet reviews git diffs and conversation history to find issues in code changes and conversation history. It is most effective when run frequently with conversation history, which helps it catch misunderstandings between what was requested and what was implemented.

## Installation

Install vet using pip or uv:

```bash
# Using pip
pip install git+https://github.com/imbue-ai/vet.git

# Using uv (recommended)
uv pip install git+https://github.com/imbue-ai/vet.git

Verify installation:
```bash
vet --help
```

## Running Vet

### Standard Usage

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

## Common Options

- `--base-commit REF`: Git ref for diff base (default: HEAD)
- `--model MODEL`: LLM model to use (default: claude-4-5-haiku)
- `--confidence-threshold N`: Minimum confidence 0.0-1.0 (default: 0.8)
- `--output-format FORMAT`: Output as `text` or `json`
- `--quiet`: Suppress progress output
- `--help`: Show comprehensive list of options

## Configuration

Create `vet.toml` in your repo for project-specific presets:

```toml
[ci]
confidence_threshold = 0.9
base_commit = "main"
quiet = true
```

Then run with `vet --config ci "goal"`.
