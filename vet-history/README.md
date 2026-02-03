# vet-history

History loader for [VET](https://github.com/imbue-ai/vet) - extracts conversation history from coding agents.

## Installation

```bash
# From the vet-history directory
pip install -e .

# Or directly
pip install ./vet-history
```

## Supported Agents

- **Claude Code** - Anthropic's official coding CLI (`~/.claude/projects/`)
- **OpenCode** - Open-source coding agent (`~/.local/share/opencode/storage/`)
- **Codex CLI** - OpenAI's Codex CLI (`~/.codex/sessions/`)

## Usage

### With VET

Use vet-history as a history loader with VET's `--history-loader` flag:

```bash
# Load latest Claude Code session
vet "Fix the bug" --history-loader "vet-history claude-code --latest"

# Load latest session for current project
vet "Refactor this" --history-loader "vet-history claude-code --project ."

# Load latest OpenCode session
vet "Add tests" --history-loader "vet-history opencode --latest"

# Load latest Codex session
vet "Update docs" --history-loader "vet-history codex --latest"
```

### Standalone

You can also use vet-history standalone to extract conversation history:

```bash
# Claude Code
vet-history claude-code --latest              # Latest session across all projects
vet-history claude-code --project .           # Latest session for current project
vet-history claude-code --session <uuid>      # Specific session by ID
vet-history claude-code --list                # List available sessions

# OpenCode
vet-history opencode --latest                 # Latest session (default)
vet-history opencode --session <id>           # Specific session
vet-history opencode --project .              # Filter by project directory
vet-history opencode --list                   # List available sessions

# Codex CLI
vet-history codex --latest                    # Latest session
vet-history codex --session <uuid>            # Specific session
vet-history codex --list                      # List available sessions
```

## Output Format

vet-history outputs JSONL (JSON Lines) to stdout, compatible with VET's history parser.

Each line is either:
- `ChatInputUserMessage` - User input
- `ResponseBlockAgentMessage` - Agent response with content blocks

Example output:
```jsonl
{"object_type":"ChatInputUserMessage","text":"Fix the login bug","source":"USER",...}
{"object_type":"ResponseBlockAgentMessage","role":"assistant","content":[{"type":"text","text":"I'll fix that..."}],...}
```

## Exit Codes

- `0` - Success, history output to stdout
- `1` - Error (no session found, parse error, etc.)
- `2` - Invalid usage/configuration

## Programmatic Usage

```python
from vet_history.loaders.claude_code import ClaudeCodeLoader
from vet_history.types import messages_to_jsonl

# Load Claude Code history
loader = ClaudeCodeLoader()
messages = loader.load_latest()

# Convert to JSONL
jsonl_output = messages_to_jsonl(messages)
print(jsonl_output)
```

## Adding New Loaders

To add support for a new coding agent:

1. Create a new loader in `vet_history/loaders/`:

```python
from vet_history.loaders.base import BaseLoader

class MyAgentLoader(BaseLoader):
    AGENT_NAME = "my-agent"
    DEFAULT_HISTORY_PATH = Path.home() / ".my-agent"

    def list_sessions(self, project_path=None):
        ...

    def get_latest_session(self, project_path=None):
        ...

    def get_session_by_id(self, session_id):
        ...

    def load_session(self, session):
        # Return list of ChatInputUserMessage / ResponseBlockAgentMessage
        ...
```

2. Add discovery utilities in `vet_history/utils/discovery.py`

3. Add CLI subcommand in `vet_history/cli.py`

4. Update `vet_history/__init__.py` and `vet_history/loaders/__init__.py`

## License

MIT
