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
from vet.imbue_core.agents.agent_api.errors import AgentCLINotFoundError
from vet.imbue_core.agents.agent_api.opencode.data_types import OpenCodeOptions
from vet.imbue_core.agents.agent_api.opencode.message_parser import parse_opencode_event
from vet.imbue_core.agents.agent_api.transport import AgentSubprocessCLITransport
from vet.imbue_core.agents.agent_api.transport import AgentSubprocessCLITransportOptions


class OpenCodeClient(RealAgentClient[OpenCodeOptions]):
    def __init__(self, options: OpenCodeOptions) -> None:
        super().__init__(options=options)

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

        cmd = self._build_cli_cmd(self._options)
        with AgentSubprocessCLITransport.build(AgentSubprocessCLITransportOptions(cmd=cmd)) as transport:
            transport.write_stdin(prompt)

            for data in transport.receive_messages():
                logger.trace(
                    "{client_name}: received raw JSON message={data}",
                    client_name=type(self).__name__,
                    data=data,
                )

                message = parse_opencode_event(data)
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
        cli = shutil.which("opencode")
        if cli:
            return cli

        locations = [
            Path("/usr/local/bin/opencode"),
            Path.home() / ".local/bin/opencode",
            Path.home() / "node_modules/.bin/opencode",
            Path.home() / ".npm-global/bin/opencode",
        ]

        for path in locations:
            if path.exists() and path.is_file():
                return str(path)

        node_installed = shutil.which("node") is not None

        if not node_installed:
            raise AgentCLINotFoundError("OpenCode CLI not found. Node.js is required but not installed.")

        raise AgentCLINotFoundError(
            "OpenCode CLI not found. Ensure it is installed and available on your PATH, or specify a different harness with --agent-harness."
        )

    @classmethod
    def _build_cli_cmd(cls, options: OpenCodeOptions) -> list[str]:
        if options.is_cached:
            cmd = ["CACHED_OPENCODE_EXEC_PLACEHOLDER"]
            return cmd
        cli_path = str(options.cli_path) if options.cli_path is not None else cls._find_cli()
        cmd = [cli_path, "run", "--format", "json"]
        cmd.extend(cls._build_cli_args(options))
        return cmd

    @staticmethod
    def _build_cli_args(options: OpenCodeOptions) -> list[str]:
        args: list[str] = []
        if options.model:
            args.extend(["--model", options.model])
        if options.cwd:
            args.extend(["--dir", str(options.cwd)])
        return args
