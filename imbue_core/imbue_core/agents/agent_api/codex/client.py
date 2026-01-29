import json
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Generator
from typing import Iterator
from typing import Self

from loguru import logger

from imbue_core.agents.agent_api.client import RealAgentClient
from imbue_core.agents.agent_api.codex.data_types import CodexOptions
from imbue_core.agents.agent_api.codex.message_parser import parse_codex_event
from imbue_core.agents.agent_api.data_types import AgentMessage
from imbue_core.agents.agent_api.data_types import AgentSystemMessage
from imbue_core.agents.agent_api.errors import AgentCLINotFoundError
from imbue_core.agents.agent_api.transport import AgentSubprocessCLITransport
from imbue_core.agents.agent_api.transport import AgentSubprocessCLITransportOptions


class CodexClient(RealAgentClient[CodexOptions]):
    """Codex CLI client implementation."""

    def __init__(self, options: CodexOptions) -> None:
        super().__init__(options=options)
        self._session_id: str | None = options.resume_session_id

    @classmethod
    @contextmanager
    def build(cls, options: CodexOptions) -> Generator[Self, None, None]:
        yield cls(options=options)

    def process_query(self, prompt: str) -> Iterator[AgentMessage]:
        logger.trace(
            "{client_name}: calling agent with prompt={prompt}", client_name=type(self).__name__, prompt=prompt
        )

        # NOTE: (2025-11-20) Codex CLI does not support streaming inputs, and only supports using codex CLI via
        # non-interactive mode, where each call is a new process.
        # So here we just create a new transport for each call, and handle things like resuming the session as
        # needed.
        options = self._options
        if self._session_id is not None and self._session_id != self._options.resume_session_id:
            # Inject the current session id into the options before building the command
            options = self._options.model_copy(update={"resume_session_id": self._session_id})
        cmd = self._build_cli_cmd(options)
        with AgentSubprocessCLITransport.build(
            AgentSubprocessCLITransportOptions(cmd=[*cmd, prompt], cwd=options.cwd)
        ) as transport:
            transport.send_request([prompt], options)

            thread_id: str | None = None
            for data in transport.receive_messages():
                logger.trace(
                    "{client_name}: received raw JSON message={data}", client_name=type(self).__name__, data=data
                )

                message = parse_codex_event(data, thread_id)
                if message:
                    if isinstance(message, AgentSystemMessage):
                        thread_id = message.session_id
                        # Store the new session id for subsequent calls to process_query on this client
                        self._session_id = message.session_id

                    yield message

        logger.trace(
            "{client_name}: finished calling agent with prompt={prompt}",
            client_name=type(self).__name__,
            prompt=prompt,
        )

    @staticmethod
    def _find_cli() -> str:
        """Find Codex CLI binary."""
        cli = shutil.which("codex")
        if cli:
            return cli

        locations = [
            Path("/usr/local/bin/codex"),
            Path.home() / ".local/bin/codex",
            Path.home() / "node_modules/.bin/codex",
            Path.home() / ".npm-global/bin/codex",
        ]

        for path in locations:
            if path.exists() and path.is_file():
                return str(path)

        node_installed = shutil.which("node") is not None
        npm_installed = shutil.which("npm") is not None

        if not node_installed or not npm_installed:
            raise AgentCLINotFoundError(
                "\n".join(
                    [
                        "Codex CLI requires Node.js and npm, which may not be installed.",
                        "Install Node.js from: https://nodejs.org/",
                        "\nAfter installing Node.js, install Codex CLI:",
                        "  npm install -g @openai/codex",
                    ]
                )
            )

        raise AgentCLINotFoundError(
            "\n".join(
                [
                    "Codex CLI not found. Install with:",
                    "  npm install -g @openai/codex",
                    "\nOr via Homebrew:",
                    "  brew install codex",
                    "\nIf already installed locally, try:",
                    '  export PATH="$HOME/node_modules/.bin:$PATH"',
                ]
            )
        )

    @classmethod
    def _build_cli_cmd(cls, options: CodexOptions) -> list[str]:
        """Build CLI command with arguments."""
        if options.is_cached:
            # in this case, the cmd should never be used
            cmd = ["CACHED_CODEX_EXEC_PLACEHOLDER"]
            return cmd
        cli_path = str(options.cli_path) if options.cli_path is not None else cls._find_cli()
        cmd = [cli_path, "exec"]
        cmd.extend(cls._build_cli_args(options))
        return cmd

    @staticmethod
    def _build_cli_args(options: CodexOptions) -> list[str]:
        args = []
        # Permissions flags
        if options.approval_mode:
            args.extend(["-c", f"'approval_mode={options.approval_mode}'"])
        if options.sandbox_mode:
            args.extend(["--sandbox", options.sandbox_mode])
        if options.approval_policy:
            args.extend(["-c", f"'approval={options.approval_policy}'"])

        # JSON streaming output
        args.append("--json")

        # Model selection
        if options.model:
            args.extend(["--model", options.model])

        # Skip git repo check
        if options.skip_git_repo_check:
            args.append("--skip-git-repo-check")

        # Output schema for structured output
        if options.output_schema:
            args.extend(["--output-schema", json.dumps(options.output_schema)])

        # Session resumption
        if options.resume_last:
            args.extend(["resume", "--last"])
        elif options.resume_session_id:
            args.extend(["resume", options.resume_session_id])
        return args
