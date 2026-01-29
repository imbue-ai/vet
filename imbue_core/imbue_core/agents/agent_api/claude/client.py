import json
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Generator
from typing import Iterator
from typing import Self

from loguru import logger

from imbue_core.agents.agent_api.claude.data_types import ClaudeCodeOptions
from imbue_core.agents.agent_api.claude.message_parser import parse_claude_message
from imbue_core.agents.agent_api.client import RealAgentClient
from imbue_core.agents.agent_api.data_types import AgentMessage
from imbue_core.agents.agent_api.data_types import AgentResultMessage
from imbue_core.agents.agent_api.errors import AgentCLINotFoundError
from imbue_core.agents.agent_api.transport import AgentSubprocessCLITransport
from imbue_core.agents.agent_api.transport import AgentSubprocessCLITransportOptions
from imbue_core.agents.agent_api.transport import AgentTransport


class ClaudeCodeClient(RealAgentClient[ClaudeCodeOptions]):
    """Claude Code client implementation.

    Most callers should obtain an instance through `get_agent_client(options=ClaudeCodeOptions(...))`,
    which takes care of building and tearing down the underlying CLI transport.

    Example:
        ```python
        with get_agent_client(options=ClaudeCodeOptions()) as client:
            for message in client.process_query(prompt="Hello"):
                print(message)
        ```
    """

    def __init__(self, options: ClaudeCodeOptions, transport: AgentTransport) -> None:
        super().__init__(options)
        self._transport = transport

    @classmethod
    @contextmanager
    def build(cls, options: ClaudeCodeOptions) -> Generator[Self, None, None]:
        cmd = cls._build_cli_cmd(options)
        with AgentSubprocessCLITransport.build(
            AgentSubprocessCLITransportOptions(
                cmd=cmd,
                cwd=options.cwd,
                extra_env_vars={"CLAUDE_CODE_ENTRYPOINT": "sdk-py"},
            )
        ) as transport:
            yield cls(options=options, transport=transport)

    def process_query(self, prompt: str) -> Iterator[AgentMessage]:
        logger.trace(
            "{client_name}: calling agent with prompt={prompt}",
            client_name=type(self).__name__,
            prompt=prompt,
        )
        # Claude code expects "User message" objects as inputs
        self._transport.send_request(
            [
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": [{"type": "text", "text": prompt}],
                    },
                }
            ],
            self._options,
        )

        for data in self._transport.receive_messages():
            logger.trace(
                "{client_name}: received raw JSON message={data}",
                client_name=type(self).__name__,
                data=data,
            )

            message = parse_claude_message(data)
            if message:
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
        """Find Claude Code CLI binary."""
        cli = shutil.which("claude")
        if cli:
            return cli

        locations = [
            # TODO: Document what these do.  Does the path to claude inside the container need to be here?
            Path("/imbue_addons/bin/claude"),
            Path.home() / ".npm-global/bin/claude",
            Path("/usr/local/bin/claude"),
            Path.home() / ".local/bin/claude",
            Path.home() / "node_modules/.bin/claude",
            Path.home() / ".yarn/bin/claude",
        ]

        for path in locations:
            if path.exists() and path.is_file():
                return str(path)

        node_installed = shutil.which("node") is not None

        if not node_installed:
            raise AgentCLINotFoundError(
                "\n".join(
                    [
                        "Claude Code requires Node.js, which is not installed.",
                        "Install Node.js from: https://nodejs.org/",
                        "\nAfter installing Node.js, install Claude Code:",
                        "  npm install -g @anthropic-ai/claude-code",
                    ]
                )
            )

        raise AgentCLINotFoundError(
            "\n".join(
                [
                    "Claude Code not found. Install with:",
                    "  npm install -g @anthropic-ai/claude-code",
                    "\nIf already installed locally, try:",
                    '  export PATH="$HOME/node_modules/.bin:$PATH"',
                ]
            )
        )

    @classmethod
    def _build_cli_cmd(cls, options: ClaudeCodeOptions) -> list[str]:
        """Build CLI command with arguments."""
        if options.is_cached:
            # in this case, the cmd should never be used
            cmd = ["CACHED_CLAUDE_CODE_EXEC_PLACEHOLDER"]
            return cmd
        cli_path = (
            str(options.cli_path) if options.cli_path is not None else cls._find_cli()
        )
        cmd = [
            cli_path,
            "--output-format",
            "stream-json",
            "--input-format",
            "stream-json",
            "--verbose",
        ]
        cmd.extend(cls._build_cli_args(options))
        return cmd

    @staticmethod
    def _build_cli_args(options: ClaudeCodeOptions) -> list[str]:
        args = []
        if options.system_prompt:
            args.extend(["--system-prompt", options.system_prompt])

        if options.append_system_prompt:
            args.extend(["--append-system-prompt", options.append_system_prompt])

        if options.model:
            args.extend(["--model", options.model])

        if options.permission_prompt_tool_name:
            args.extend(
                ["--permission-prompt-tool", options.permission_prompt_tool_name]
            )

        if options.permission_mode:
            args.extend(["--permission-mode", options.permission_mode])

        if options.continue_conversation:
            args.append("--continue")

        if options.resume:
            args.extend(["--resume", options.resume])

        if options.mcp_servers:
            mcp_config_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
            mcp_config_file.write(
                json.dumps(
                    {
                        "mcpServers": {
                            k: v.model_dump() for k, v in options.mcp_servers.items()
                        }
                    }
                ).encode("utf-8")
            )
            args.extend(["--mcp-config", mcp_config_file.name])

        args.append("--print")
        return args
