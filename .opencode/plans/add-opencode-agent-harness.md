# Plan: Add OpenCode Agent Harness

## Overview

Add OpenCode as a third agent harness alongside Claude Code and Codex. OpenCode would be invoked via `opencode run --format json <prompt>` and its JSONL output parsed into the unified `AgentMessage` types.

## Architecture Match

The existing pattern is a 4-file package per agent under `vet/imbue_core/agents/agent_api/<agent>/`:

```
opencode/
  __init__.py        # empty
  client.py          # OpenCodeClient(RealAgentClient)
  data_types.py      # OpenCodeOptions + event types + OPENCODE_TOOLS
  message_parser.py  # parse_opencode_event() -> AgentMessage
```

Plus modifications to 3 existing files for wiring.

## Detailed Changes

### 1. `vet/imbue_core/data_types.py` (line 170-172) — +1 LoC

Add `OPENCODE = "opencode"` to `AgentHarnessType` enum.

```python
class AgentHarnessType(StrEnum):
    CLAUDE = "claude"
    CODEX = "codex"
    OPENCODE = "opencode"  # NEW
```

### 2. `vet/imbue_core/agents/agent_api/opencode/__init__.py` — 0 LoC

Empty file.

### 3. `vet/imbue_core/agents/agent_api/opencode/data_types.py` — ~90 LoC

Define `OpenCodeOptions(AgentOptions)` following the `CodexOptions`/`ClaudeCodeOptions` pattern:

```python
from pathlib import Path
from typing import Any, Literal
from pydantic import Field
from vet.imbue_core.agents.agent_api.data_types import AgentOptions, AgentToolName
from vet.imbue_core.pydantic_serialization import SerializableModel


class OpenCodeOptions(AgentOptions):
    """Options for OpenCode CLI execution."""
    object_type: Literal["OpenCodeOptions"] = "OpenCodeOptions"
    model: str | None = None
    agent: str | None = None
    continue_session: bool = False
    session_id: str | None = None
    fork: bool = False
    dir: str | Path | None = None
    variant: str | None = None
    cli_path: Path | None = None
    is_cached: bool = False


# OpenCode JSON event data types (from `opencode run --format json`)

class OpenCodeTokens(SerializableModel):
    total: int
    input: int
    output: int
    reasoning: int
    cache: dict[str, int] | None = None


class OpenCodeStepStartPart(SerializableModel):
    id: str
    sessionID: str
    messageID: str
    type: Literal["step-start"]
    snapshot: str | None = None


class OpenCodeTextPart(SerializableModel):
    id: str
    sessionID: str
    messageID: str
    type: Literal["text"]
    text: str
    time: dict[str, int] | None = None


class OpenCodeToolState(SerializableModel):
    status: str
    input: dict[str, Any] = Field(default_factory=dict)
    output: str | None = None
    title: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    time: dict[str, int] | None = None


class OpenCodeToolUsePart(SerializableModel):
    id: str
    sessionID: str
    messageID: str
    type: Literal["tool"]
    callID: str
    tool: str
    state: OpenCodeToolState


class OpenCodeStepFinishPart(SerializableModel):
    id: str
    sessionID: str
    messageID: str
    type: Literal["step-finish"]
    reason: str
    snapshot: str | None = None
    cost: float | None = None
    tokens: OpenCodeTokens | None = None


class OpenCodeEvent(SerializableModel):
    type: str
    timestamp: int
    sessionID: str
    part: dict[str, Any]  # We parse part based on type


OPENCODE_TOOLS = (
    AgentToolName.READ,
    AgentToolName.WRITE,
    AgentToolName.EDIT,
    AgentToolName.MULTI_EDIT,
    AgentToolName.GLOB,
    AgentToolName.GREP,
    AgentToolName.LS,
    AgentToolName.BASH,
    AgentToolName.BASH_OUTPUT,
    AgentToolName.KILL_SHELL,
    AgentToolName.WEB_SEARCH,
    AgentToolName.WEB_FETCH,
    AgentToolName.TASK,
    AgentToolName.TODO_READ,
    AgentToolName.TODO_WRITE,
)
```

### 4. `vet/imbue_core/agents/agent_api/opencode/message_parser.py` — ~90 LoC

Parse OpenCode JSONL events into unified `AgentMessage` types:

```python
from typing import Any
from vet.imbue_core.agents.agent_api.data_types import (
    AgentAssistantMessage, AgentMessage, AgentResultMessage,
    AgentSystemEventType, AgentSystemMessage, AgentTextBlock,
    AgentToolResultBlock, AgentToolUseBlock, AgentUnknownMessage, AgentUsage,
)


def parse_opencode_event(data: dict[str, Any]) -> AgentMessage | None:
    """Parse OpenCode JSON event into unified message type.

    OpenCode `run --format json` emits JSONL with these event types:
    - step_start: a new agent step begins
    - text: agent text output
    - tool_use: tool invocation with input/output
    - step_finish: step completed with cost/token info
    """
    event_type = data.get("type", "")
    part = data.get("part", {})
    session_id = data.get("sessionID", "")

    match event_type:
        case "step_start":
            return AgentSystemMessage(
                event_type=AgentSystemEventType.SESSION_STARTED,
                session_id=session_id,
                original_message=data,
            )

        case "text":
            text = part.get("text", "")
            return AgentAssistantMessage(
                content=[AgentTextBlock(text=text)],
                original_message=data,
            )

        case "tool_use":
            state = part.get("state", {})
            tool_name = part.get("tool", "unknown")
            call_id = part.get("callID", part.get("id", ""))
            tool_input = state.get("input", {})

            content_blocks = []

            # Tool use request
            content_blocks.append(AgentToolUseBlock(
                id=call_id,
                name=tool_name,
                input=tool_input,
            ))

            # If the tool has completed, also emit a result block
            if state.get("status") == "completed":
                output = state.get("output", "")
                metadata = state.get("metadata", {})
                exit_code = metadata.get("exit") if metadata else None
                content_blocks.append(AgentToolResultBlock(
                    tool_use_id=call_id,
                    content=output,
                    is_error=exit_code is not None and exit_code != 0,
                    exit_code=exit_code,
                ))

            return AgentAssistantMessage(
                content=content_blocks,
                original_message=data,
            )

        case "step_finish":
            tokens_data = part.get("tokens")
            usage = None
            if tokens_data:
                cache = tokens_data.get("cache", {})
                usage = AgentUsage(
                    input_tokens=tokens_data.get("input"),
                    output_tokens=tokens_data.get("output"),
                    cached_tokens=cache.get("read") if cache else None,
                    total_tokens=tokens_data.get("total"),
                    thinking_tokens=tokens_data.get("reasoning") or None,
                    total_cost_usd=part.get("cost"),
                )

            reason = part.get("reason", "")
            is_final = reason == "stop"

            if is_final:
                return AgentResultMessage(
                    session_id=session_id,
                    is_error=False,
                    usage=usage,
                    original_message=data,
                )

            # Non-final step_finish (e.g., reason="tool-calls") -> system event
            return AgentSystemMessage(
                event_type=AgentSystemEventType.TURN_COMPLETED,
                session_id=session_id,
                original_message=data,
            )

        case _:
            return AgentUnknownMessage(raw=data, original_message=data)
```

### 5. `vet/imbue_core/agents/agent_api/opencode/client.py` — ~130 LoC

Following the Codex pattern (new subprocess per query since `opencode run` is one-shot):

```python
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Iterator, Self

from loguru import logger

from vet.imbue_core.agents.agent_api.client import RealAgentClient
from vet.imbue_core.agents.agent_api.opencode.data_types import OpenCodeOptions
from vet.imbue_core.agents.agent_api.opencode.message_parser import parse_opencode_event
from vet.imbue_core.agents.agent_api.data_types import AgentMessage, AgentResultMessage, AgentSystemMessage
from vet.imbue_core.agents.agent_api.errors import AgentCLINotFoundError
from vet.imbue_core.agents.agent_api.transport import (
    AgentSubprocessCLITransport,
    AgentSubprocessCLITransportOptions,
)


class OpenCodeClient(RealAgentClient[OpenCodeOptions]):
    """OpenCode CLI client implementation."""

    def __init__(self, options: OpenCodeOptions) -> None:
        super().__init__(options=options)
        self._session_id: str | None = options.session_id

    @classmethod
    @contextmanager
    def build(cls, options: OpenCodeOptions) -> Generator[Self, None, None]:
        yield cls(options=options)

    def process_query(self, prompt: str) -> Iterator[AgentMessage]:
        logger.trace(
            "{client_name}: calling agent with prompt={prompt}",
            client_name=type(self).__name__,
            prompt=prompt,
        )

        options = self._options
        if self._session_id is not None and self._session_id != self._options.session_id:
            options = self._options.model_copy(update={"session_id": self._session_id})

        cmd = self._build_cli_cmd(options)
        with AgentSubprocessCLITransport.build(
            AgentSubprocessCLITransportOptions(
                cmd=[*cmd, prompt],
                cwd=options.cwd or options.dir,
            )
        ) as transport:
            # OpenCode run doesn't need stdin messages - prompt is in args
            transport.send_request([], options)

            for data in transport.receive_messages():
                logger.trace(
                    "{client_name}: received raw JSON message={data}",
                    client_name=type(self).__name__,
                    data=data,
                )

                message = parse_opencode_event(data)
                if message is None:
                    continue

                # Track session ID from events
                if isinstance(message, (AgentSystemMessage, AgentResultMessage)):
                    event_session_id = getattr(message, "session_id", None)
                    if event_session_id:
                        self._session_id = event_session_id

                yield message

                if isinstance(message, AgentResultMessage):
                    break

        logger.trace(
            "{client_name}: finished calling agent with prompt={prompt}",
            client_name=type(self).__name__,
            prompt=prompt,
        )

    @staticmethod
    def _find_cli() -> str:
        """Find OpenCode CLI binary."""
        cli = shutil.which("opencode")
        if cli:
            return cli

        locations = [
            Path("/usr/local/bin/opencode"),
            Path.home() / ".local/bin/opencode",
            Path.home() / "go/bin/opencode",
        ]

        for path in locations:
            if path.exists() and path.is_file():
                return str(path)

        raise AgentCLINotFoundError(
            "\n".join([
                "OpenCode CLI not found. Install with:",
                "  curl -fsSL https://opencode.ai/install | bash",
                "\nOr via Go:",
                "  go install github.com/anomalyco/opencode@latest",
                "\nIf already installed, try:",
                '  export PATH="$HOME/.local/bin:$PATH"',
            ])
        )

    @classmethod
    def _build_cli_cmd(cls, options: OpenCodeOptions) -> list[str]:
        """Build CLI command with arguments."""
        if options.is_cached:
            cmd = ["CACHED_OPENCODE_EXEC_PLACEHOLDER"]
            return cmd
        cli_path = str(options.cli_path) if options.cli_path is not None else cls._find_cli()
        cmd = [cli_path, "run", "--format", "json"]
        cmd.extend(cls._build_cli_args(options))
        return cmd

    @staticmethod
    def _build_cli_args(options: OpenCodeOptions) -> list[str]:
        args = []
        if options.model:
            args.extend(["--model", options.model])
        if options.agent:
            args.extend(["--agent", options.agent])
        if options.continue_session:
            args.append("--continue")
        elif options.session_id:
            args.extend(["--session", options.session_id])
        if options.fork:
            args.append("--fork")
        if options.dir:
            args.extend(["--dir", str(options.dir)])
        if options.variant:
            args.extend(["--variant", options.variant])
        return args
```

### 6. `vet/imbue_core/agents/agent_api/api.py` — +6 LoC

Add import and singledispatch registration:

```python
# Add imports (after existing ones)
from vet.imbue_core.agents.agent_api.opencode.client import OpenCodeClient
from vet.imbue_core.agents.agent_api.opencode.data_types import OpenCodeOptions

# Add registration (after CodexOptions registration)
@_build_client_from_options.register
def _(options: OpenCodeOptions) -> ContextManager[AgentClient[OpenCodeOptions]]:
    return OpenCodeClient.build(options)
```

### 7. `vet/issue_identifiers/common.py` (line 203-238) — +12 LoC

Add OpenCode branch in `get_agent_options()`:

```python
# Add import
from vet.imbue_core.agents.agent_api.opencode.data_types import OpenCodeOptions

# Add branch in get_agent_options(), after the CODEX branch:
    if agent_harness_type == AgentHarnessType.OPENCODE:
        # OpenCode supports multiple providers via --model provider/model format
        # so we can pass through most model names directly
        return OpenCodeOptions(
            cwd=cwd,
            model=model_name,
        )
```

### 8. No change needed to `vet/cli/main.py`

The `--agent-harness` argument already uses `choices=list(AgentHarnessType)`, so adding `OPENCODE` to the enum automatically makes `--agent-harness opencode` a valid CLI option.

## Line Count Summary

| File | New/Modified | LoC |
|------|-------------|-----|
| `data_types.py` | Modified | +1 |
| `opencode/__init__.py` | New | 0 |
| `opencode/data_types.py` | New | ~90 |
| `opencode/message_parser.py` | New | ~90 |
| `opencode/client.py` | New | ~130 |
| `api.py` | Modified | +6 |
| `common.py` | Modified | +12 |
| **Total** | | **~330** |

## Usage

After implementation:

```bash
# Run vet in agentic mode using OpenCode
vet --agentic --agent-harness opencode "Review the changes in this PR"

# With a specific model
vet --agentic --agent-harness opencode --model anthropic/claude-sonnet-4 "Check for bugs"
```
