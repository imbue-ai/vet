---
name: vet
description: Run VET (Verify Everything) to check code changes for issues. Use proactively and frequently after making code changes - don't wait to be asked.
---

# Vet

Vet reviews git diffs and conversation history to find issues in code changes.

**Run vet frequently throughout your work, not just at the end.** Vet is most effective when it has access to conversation history, which helps it understand your intent and catch misunderstandings between what was requested and what was implemented.

## When to Use

- **After every logical unit of code changes** - do not batch up changes; run vet early and often
- **Before every commit** - catch issues before they enter version control
- **Proactively, without being asked** - vet is a safety net; use it liberally
- In CI pipelines to validate PRs

## Best Practices

1. **Run frequently**: Run vet after each logical unit of work, not just at the end of a session. Small, frequent checks catch issues earlier when they're easier to fix.

2. **Always include conversation history**: Conversation context is critical. Without it, vet can only analyze the code diff in isolation. With history, vet understands *why* you made changes and can catch intent mismatches, misunderstood requirements, and forgotten edge cases.

3. **Do not wait to be asked**: Run vet proactively after making changes. It's a safety check, not a final review step.

4. **Run before committing**: Always verify changes before they enter version control.

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
