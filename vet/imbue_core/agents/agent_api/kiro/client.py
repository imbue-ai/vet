import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from typing import Generator
from typing import Iterator
from typing import Self

from loguru import logger

from vet.imbue_core.agents.agent_api.client import RealAgentClient
from vet.imbue_core.agents.agent_api.data_types import AgentAssistantMessage
from vet.imbue_core.agents.agent_api.data_types import AgentMessage
from vet.imbue_core.agents.agent_api.data_types import AgentResultMessage
from vet.imbue_core.agents.agent_api.data_types import AgentTextBlock
from vet.imbue_core.agents.agent_api.errors import AgentCLINotFoundError
from vet.imbue_core.agents.agent_api.errors import AgentProcessError
from vet.imbue_core.agents.agent_api.kiro.data_types import KiroOptions
from vet.imbue_core.agents.agent_api.kiro.message_parser import parse_kiro_message
from vet.imbue_core.agents.agent_api.transport import AgentSubprocessCLITransport
from vet.imbue_core.agents.agent_api.transport import AgentSubprocessCLITransportOptions
from vet.imbue_core.agents.agent_api.transport import AgentTransport

_REQ_ID_INIT = 0
_REQ_ID_SESSION_NEW = 1
_REQ_ID_PROMPT = 2


class KiroClient(RealAgentClient[KiroOptions]):
    """Kiro CLI client implementation.

    Speaks ACP (Agent Client Protocol), JSON-RPC 2.0 over stdio, via `kiro-cli acp`.
    Unlike Claude Code's ACP-adjacent stream-json protocol, Kiro's turn-end signal
    is the JSON-RPC response to the `session/prompt` request itself (carrying a
    `stopReason`), not a separate notification.
    """

    def __init__(self, options: KiroOptions, transport: AgentTransport) -> None:
        super().__init__(options)
        self._transport = transport

    @classmethod
    @contextmanager
    def build(cls, options: KiroOptions) -> Generator[Self, None, None]:
        cmd = cls._build_cli_cmd(options)
        with AgentSubprocessCLITransport.build(
            AgentSubprocessCLITransportOptions(cmd=cmd, cwd=options.cwd)
        ) as transport:
            yield cls(options=options, transport=transport)

    def process_query(self, prompt: str) -> Iterator[AgentMessage]:
        logger.trace(
            "{client_name}: calling agent with prompt={prompt}",
            client_name=type(self).__name__,
            prompt=prompt,
        )

        stream = self._transport.receive_messages()

        self._transport.send_request(
            [
                {
                    "jsonrpc": "2.0",
                    "id": _REQ_ID_INIT,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": 1,
                        "clientCapabilities": {},
                        "clientInfo": {"name": "vet", "version": "0.1"},
                    },
                }
            ],
            self._options,
        )
        _drain_until_id(stream, _REQ_ID_INIT)

        cwd = str(self._options.cwd) if self._options.cwd is not None else str(Path.cwd())
        self._transport.send_request(
            [
                {
                    "jsonrpc": "2.0",
                    "id": _REQ_ID_SESSION_NEW,
                    "method": "session/new",
                    "params": {"cwd": cwd, "mcpServers": []},
                }
            ],
            self._options,
        )
        session_new_response = _drain_until_id(stream, _REQ_ID_SESSION_NEW)
        session_id = session_new_response.get("result", {}).get("sessionId", "")

        session_message = parse_kiro_message(session_new_response)
        if session_message is not None:
            yield session_message

        self._transport.send_request(
            [
                {
                    "jsonrpc": "2.0",
                    "id": _REQ_ID_PROMPT,
                    "method": "session/prompt",
                    "params": {"sessionId": session_id, "prompt": [{"type": "text", "text": prompt}]},
                }
            ],
            self._options,
        )

        # Kiro streams the response as many small text chunks (e.g. "p", "ong").
        # We accumulate them here and set the concatenation as AgentResultMessage.result
        # below, so vet's response-extraction logic (which prefers `result` and only
        # falls back to per-block "\n"-joined concatenation) sees the answer intact --
        # the fallback path would inject newlines at arbitrary chunk boundaries.
        response_text = ""
        for data in stream:
            logger.trace(
                "{client_name}: received raw JSON message={data}",
                client_name=type(self).__name__,
                data=data,
            )

            if data.get("id") == _REQ_ID_PROMPT:
                if "error" in data:
                    yield AgentResultMessage(
                        session_id=session_id,
                        is_error=True,
                        result=response_text or None,
                        error=str(data["error"]),
                        original_message=data,
                    )
                    break

                stop_reason = data.get("result", {}).get("stopReason", "")
                is_error = stop_reason != "end_turn"
                yield AgentResultMessage(
                    session_id=session_id,
                    is_error=is_error,
                    result=response_text or None,
                    error=stop_reason if is_error else None,
                    original_message=data,
                )
                break

            message = parse_kiro_message(data)
            if message is None:
                continue

            if isinstance(message, AgentAssistantMessage):
                for block in message.content:
                    if isinstance(block, AgentTextBlock):
                        response_text += block.text

            yield message

        logger.trace(
            "{client_name}: finished calling agent with prompt={prompt}",
            client_name=type(self).__name__,
            prompt=prompt,
        )

    @staticmethod
    def _find_cli() -> str:
        """Find Kiro CLI binary."""
        for name in ("kiro-cli", "kiro"):
            cli = shutil.which(name)
            if cli:
                return cli

        locations = [
            Path.home() / ".local/bin/kiro-cli",
            Path("/usr/local/bin/kiro-cli"),
            Path.home() / ".local/bin/kiro",
        ]

        for path in locations:
            if path.exists() and path.is_file():
                return str(path)

        raise AgentCLINotFoundError(
            "Kiro CLI not found. Ensure it is installed and available on your PATH, or specify a different harness with --agent-harness."
        )

    @classmethod
    def _build_cli_cmd(cls, options: KiroOptions) -> list[str]:
        """Build CLI command with arguments."""
        if options.is_cached:
            # in this case, the cmd should never be used
            cmd = ["CACHED_KIRO_EXEC_PLACEHOLDER"]
            return cmd
        cli_path = str(options.cli_path) if options.cli_path is not None else cls._find_cli()
        cmd = [cli_path, "acp", "--trust-all-tools"]
        cmd.extend(cls._build_cli_args(options))
        return cmd

    @staticmethod
    def _build_cli_args(options: KiroOptions) -> list[str]:
        args: list[str] = []
        if options.model:
            args.extend(["--model", options.model])
        if options.agent:
            args.extend(["--agent", options.agent])
        return args


def _drain_until_id(stream: Iterator[dict[str, Any]], target_id: int) -> dict[str, Any]:
    """Read from the stream until a JSON-RPC response with the given id arrives.

    Raises AgentProcessError if a JSON-RPC error response for that id arrives instead
    (e.g. an auth failure surfacing before session/new can succeed), or if the stream
    ends without ever producing a response for target_id (e.g. the CLI crashed or
    closed its stdout early).
    """
    for data in stream:
        if data.get("id") == target_id:
            if "error" in data:
                raise AgentProcessError(f"Kiro CLI returned an error: {data['error']}")
            return data
    raise AgentProcessError(f"Kiro CLI closed the stream before responding to request id {target_id}")
