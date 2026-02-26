---
name: vet
description: Run vet immediately after ANY logical unit of code changes. Do not batch your changes, do not wait to be asked to run vet, make sure you are proactive.
---

# Vet

**Run vet immediately after ANY logical unit of code changes. Do not batch changes, do not wait to be asked to run vet, make sure you are proactive.**

Vet reviews git diffs and conversation history to find issues in code changes and conversation history. It is most effective when run frequently with conversation history, which helps it catch misunderstandings between what was requested and what was implemented. Despite this, vet is not a replacement for running tests.

## Installation

Install vet using pip, pipx, or uv:

```bash
# Using pip
pip install verify-everything

# Using pipx
pipx install verify-everything

# Using uv
uv tool install verify-everything

# Verify installation:
vet --help
```

## Running Vet

### Standard Usage

Before running vet, determine the correct Python binary:
```bash
$(command -v python3 || command -v python)
```
Use whichever resolves (prefer `python3`). The examples below use `python3`, substitute `python` if that is what your system provides.

**OpenCode:**
```bash
vet "goal" --history-loader "python3 ~/.agents/skills/vet/scripts/export_opencode_session.py --session-id <ses_ID>"
```

**Codex:**
```bash
vet "goal" --history-loader "python3 ~/.codex/skills/vet/scripts/export_codex_session.py --session-file <path-to-session.jsonl>"
```

**Claude Code:**
```bash
vet "goal" --history-loader "python3 ~/.claude/skills/vet/scripts/export_claude_code_session.py --session-file <path-to-session.jsonl>"
```

**Without Conversation History**
```bash
vet "goal"
```

### Finding Your Session

You should only search for sessions from your coding harness. If a user requests you use a different harness, they are likely referring to vet's agentic mode, not the session.

**OpenCode:** The `--session-id` argument requires a `ses_...` session ID. To find the current session ID:
1. Run: `opencode session list --format json` to list recent sessions with their IDs and titles.
2. Identify the current session from the list by matching the title or timestamp.
    - IMPORTANT: Verify the session you found matches the current conversation. If the title is ambiguous, compare timestamps or check multiple candidates.
3. Pass the session ID as `--session-id`.

**Codex:** Session files are stored in `~/.codex/sessions/YYYY/MM/DD/`. To find the correct session file:
1. Find the most unique sentence / question / string in the current conversation.
2. Run: `grep -rl "UNIQUE_MESSAGE" ~/.codex/sessions/` to find the matching session file.
    - IMPORTANT: Verify the conversation you found matches the current conversation and that it is not another conversation with the same search string.
3. Pass the matched file path as `--session-file`.

**Claude Code:** Session files are stored in `~/.claude/projects/<encoded-path>/`. The encoded path replaces `/` with `-` (e.g. `/home/user/myproject` becomes `-home-user-myproject`). To find the correct session file:
1. Find the most unique sentence / question / string in the current conversation.
2. Run: `grep -rl "UNIQUE_MESSAGE" ~/.claude/projects/` to find the matching session file.
    - IMPORTANT: Verify the conversation you found matches the current conversation and that it is not another conversation with the same search string.
3. Pass the matched file path as `--session-file`.

NOTE: The examples in the standard usage section assume the user installed the vet skill at the user level, not the project level. Prior to trying to run vet, check if it was installed at the project level which should take precedence over the user level. If it is installed at the project level, ensure the history-loader option points to the correct location.

## Interpreting Results

Vet analyzes the full git diff from the base commit. This may include changes from other agents or sessions working in the same repository. If vet reports issues that relate to changes you did not make in this session, disregard them, assuming they belong to another agent or the user.

## Common Options

- `--base-commit REF`: Git ref for diff base (default: HEAD)
- `--model MODEL`: LLM model to use (default: claude-opus-4-6)
- `--confidence-threshold N`: Minimum confidence 0.0-1.0 (default: 0.8)
- `--output-format FORMAT`: Output as `text`, `json`, or `github`
- `--quiet`: Suppress status messages and 'No issues found.'
- `--agentic`: Mode that routes analysis through the locally installed Claude Code or Codex CLI instead of calling the API directly. Try this if vet fails due to missing API keys. This is slower (~3 min) so it is not the default, but it often results in higher precision issue identification.
- `--agent-harness`: The two options for this are `codex` and `claude`. Claude Code is the default.
- `--help`: Show comprehensive list of options

## Updating

The vet CLI, skill files, and export scripts can become outdated as agent harnesses and LLM APIs change.

If vet or the export scripts fail unexpectedly, try updating them. Run `which vet` to determine how vet was installed and update accordingly. For the skill files, check which skill directories exist on disk and update them with the latest versions from https://github.com/imbue-ai/vet/tree/main/skills/vet.
