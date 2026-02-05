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

Always include conversation history for best results. Pass the session identifier to the export script via `--history-loader`:

**OpenCode:**
```bash
vet "goal" --history-loader "python ~/.agents/skills/vet/scripts/export_opencode_session.py --session-id <session-uuid>"
```

**Codex:**
```bash
vet "goal" --history-loader "python ~/.codex/skills/vet/scripts/export_codex_session.py --session-file <path-to-session.jsonl>"
```

**Claude Code:**
```bash
vet "goal" --history-loader "python ~/.claude/skills/vet/scripts/export_claude_code_session.py --session-file <path-to-session.jsonl>"
```

### Finding Your Session

**OpenCode:** The session ID appears in task metadata or can be found as the most recent file in `~/.local/share/opencode/storage/session/`.

**Codex:** Session files are stored in `~/.codex/sessions/YYYY/MM/DD/`. Find the most recently modified `.jsonl` file.

**Claude Code:** Session files are stored in `~/.claude/projects/<encoded-path>/`. The encoded path replaces `/` with `-` (e.g. `/home/user/myproject` becomes `-home-user-myproject`). Find the most recently modified `.jsonl` file in the directory matching your project.

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
