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

**OpenCode:**
```bash
vet "goal" --history-loader "python ~/.agents/skills/vet/scripts/export_opencode_session.py --session-id <ses_ID>"
```

**Codex:**
```bash
vet "goal" --history-loader "python ~/.codex/skills/vet/scripts/export_codex_session.py --session-file <path-to-session.jsonl>"
```

**Claude Code:**
```bash
vet "goal" --history-loader "python ~/.claude/skills/vet/scripts/export_claude_code_session.py --session-file <path-to-session.jsonl>"
```

**Without Conversation History**
```bash
vet "goal"
```

### Finding Your Session

**OpenCode:** The `--session-id` argument requires a `ses_...` session ID. To find the current session ID, search for the first user message from this conversation in the part files:
1. Find the most unique sentence / question / string in the current conversation.
2. Run: `grep -rl "UNIQUE_MESSAGE" ~/.local/share/opencode/storage/part/` to find the matching part file.
    - IMPORTANT: Verify the conversation you found matches the current conversation, and is not another conversation with the same search string. Repeat steps 1 and 2 until you have verified the session you found is the current conversation.
3. Read the `sessionID` field from that part JSON file.
4. Pass that value as `--session-id`.

**Codex:** Session files are stored in `~/.codex/sessions/YYYY/MM/DD/`. Find the correct conversation using the approach described above for opencode that uses textual search.

**Claude Code:** Session files are stored in `~/.claude/projects/<encoded-path>/`. The encoded path replaces `/` with `-` (e.g. `/home/user/myproject` becomes `-home-user-myproject`). Find the correct conversation using the approach described above for opencode that uses textual search.

## Common Options

- `--base-commit REF`: Git ref for diff base (default: HEAD)
- `--model MODEL`: LLM model to use (default: claude-4-5-sonnet)
- `--confidence-threshold N`: Minimum confidence 0.0-1.0 (default: 0.8)
- `--output-format FORMAT`: Output as `text` or `json`
- `--quiet`: Suppress progress output
- `--help`: Show comprehensive list of options
