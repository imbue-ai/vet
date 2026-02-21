import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Generator
from typing import Iterator
from typing import Self

from loguru import logger

from vet.imbue_core.agents.agent_api.client import RealAgentClient
from vet.imbue_core.agents.agent_api.data_types import AgentMessage
from vet.imbue_core.agents.agent_api.data_types import AgentResultMessage
from vet.imbue_core.agents.agent_api.data_types import AgentSystemMessage
from vet.imbue_core.agents.agent_api.errors import AgentCLINotFoundError
from vet.imbue_core.agents.agent_api.opencode.data_types import OpenCodeOptions
from vet.imbue_core.agents.agent_api.opencode.message_parser import parse_opencode_event
from vet.imbue_core.agents.agent_api.transport import AgentSubprocessCLITransport
from vet.imbue_core.agents.agent_api.transport import AgentSubprocessCLITransportOptions


class OpenCodeClient(RealAgentClient[OpenCodeOptions]):
    """OpenCode CLI client implementation.

    Like Codex, OpenCode's `run` command is a one-shot process (not a long-lived
    stdin/stdout stream like Claude Code). A new subprocess transport is created
    for each `process_query()` call, with session continuity handled via
    `--continue` / `--session <id>`.

    Reference: `opencode run --help`
    """

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

        # NOTE: Like Codex, OpenCode CLI does not support streaming inputs.
        # Each call is a new process. Session continuity is managed via --session <id>.
        options = self._options
        if (
            self._session_id is not None
            and self._session_id != self._options.session_id
        ):
            # Inject the current session id into the options before building the command
            options = self._options.model_copy(update={"session_id": self._session_id})

        cmd = self._build_cli_cmd(options)
        with AgentSubprocessCLITransport.build(
            AgentSubprocessCLITransportOptions(
                cmd=[*cmd, prompt],
                cwd=options.cwd or options.dir,
            )
        ) as transport:
            # OpenCode run doesn't need stdin messages - prompt is passed as a positional arg.
            # Close stdin immediately so the process doesn't block waiting for input.
            transport.close_stdin()

            for data in transport.receive_messages():
                logger.trace(
                    "{client_name}: received raw JSON message={data}",
                    client_name=type(self).__name__,
                    data=data,
                )

                message = parse_opencode_event(data)
                if message is None:
                    continue

                # Track session ID from events for potential multi-turn sessions
                if isinstance(message, AgentSystemMessage) and message.session_id:
                    self._session_id = message.session_id
                elif isinstance(message, AgentResultMessage) and message.session_id:
                    self._session_id = message.session_id

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
            "\n".join(
                [
                    "OpenCode CLI not found. Install with:",
                    "  curl -fsSL https://opencode.ai/install | bash",
                    "\nIf already installed, try:",
                    '  export PATH="$HOME/.local/bin:$PATH"',
                ]
            )
        )

    @classmethod
    def _build_cli_cmd(cls, options: OpenCodeOptions) -> list[str]:
        """Build CLI command with arguments."""
        if options.is_cached:
            # in this case, the cmd should never be used
            cmd = ["CACHED_OPENCODE_EXEC_PLACEHOLDER"]
            return cmd
        cli_path = (
            str(options.cli_path) if options.cli_path is not None else cls._find_cli()
        )
        cmd = [cli_path, "run", "--format", "json"]
        cmd.extend(cls._build_cli_args(options))
        return cmd

    @staticmethod
    def _build_cli_args(options: OpenCodeOptions) -> list[str]:
        args = []
        # Model selection (OpenCode uses provider/model format, e.g., "anthropic/claude-sonnet-4")
        if options.model:
            args.extend(["--model", options.model])

        # Agent selection
        if options.agent:
            args.extend(["--agent", options.agent])

        # Session management
        if options.continue_session:
            args.append("--continue")
        elif options.session_id:
            args.extend(["--session", options.session_id])

        # Fork session
        if options.fork:
            args.append("--fork")

        # Working directory
        if options.dir:
            args.extend(["--dir", str(options.dir)])

        # Model variant (e.g., reasoning effort)
        if options.variant:
            args.extend(["--variant", options.variant])

        return args
