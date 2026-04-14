"""Client implementation for Gemini CLI."""

import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Generator
from typing import Iterator
from typing import Self

from loguru import logger

from vet.imbue_core.agents.agent_api.client import RealAgentClient
from vet.imbue_core.agents.agent_api.data_types import AgentMessage
from vet.imbue_core.agents.agent_api.data_types import AgentSystemMessage
from vet.imbue_core.agents.agent_api.errors import AgentCLINotFoundError
from vet.imbue_core.agents.agent_api.gemini.data_types import GeminiOptions
from vet.imbue_core.agents.agent_api.gemini.message_parser import parse_gemini_event
from vet.imbue_core.agents.agent_api.transport import AgentSubprocessCLITransport
from vet.imbue_core.agents.agent_api.transport import AgentSubprocessCLITransportOptions


class GeminiClient(RealAgentClient[GeminiOptions]):
    """Gemini CLI client implementation."""

    def __init__(self, options: GeminiOptions) -> None:
        super().__init__(options=options)

    @classmethod
    @contextmanager
    def build(cls, options: GeminiOptions) -> Generator[Self, None, None]:
        yield cls(options=options)

    def process_query(self, prompt: str) -> Iterator[AgentMessage]:
        logger.trace(
            "{client_name}: calling agent with prompt length={prompt_length}",
            client_name=type(self).__name__,
            prompt_length=len(prompt),
        )

        options = self._options
        cmd = self._build_cli_cmd(options)

        with AgentSubprocessCLITransport.build(
            AgentSubprocessCLITransportOptions(cmd=cmd, cwd=options.cwd)
        ) as transport:
            transport.write_stdin(prompt)

            thread_id: str | None = None
            for data in transport.receive_messages():
                logger.trace(
                    "{client_name}: received raw JSON message={data}",
                    client_name=type(self).__name__,
                    data=data,
                )

                message = parse_gemini_event(data, thread_id)
                if isinstance(message, AgentSystemMessage) and message.session_id:
                    thread_id = message.session_id

                yield message

        logger.trace(
            "{client_name}: finished calling agent",
            client_name=type(self).__name__,
        )

    @staticmethod
    def _find_cli() -> str:
        """Find Gemini CLI binary."""
        cli = shutil.which("gemini")
        if cli:
            return cli

        raise AgentCLINotFoundError(
            "Gemini CLI not found. Ensure it is installed and available on your PATH, or specify a different harness with --agent-harness."
        )

    @classmethod
    def _build_cli_cmd(cls, options: GeminiOptions) -> list[str]:
        """Build CLI command with arguments."""
        cli_path = str(options.cli_path) if options.cli_path is not None else cls._find_cli()
        cmd = [cli_path]
        cmd.extend(cls._build_cli_args(options))
        return cmd

    @staticmethod
    def _build_cli_args(options: GeminiOptions) -> list[str]:
        """Build CLI arguments for the agent."""
        args = ["-p", "-", "-o", "stream-json"]

        if options.model:
            args.extend(["--model", options.model])

        return args
