import json
import os
import subprocess
import threading
from abc import ABC
from abc import abstractmethod
from contextlib import contextmanager
from pathlib import Path
from subprocess import PIPE
from typing import Any
from typing import ContextManager
from typing import Generator
from typing import Generic
from typing import Iterable
from typing import Iterator
from typing import Self
from typing import Sequence
from typing import TypeVar

from vet.imbue_core.agents.agent_api.data_types import AgentOptions
from vet.imbue_core.agents.agent_api.errors import AgentCLIConnectionError
from vet.imbue_core.agents.agent_api.errors import AgentCLIJSONDecodeError as SDKJSONDecodeError
from vet.imbue_core.agents.agent_api.errors import AgentCLINotFoundError
from vet.imbue_core.agents.agent_api.errors import AgentProcessError
from vet.imbue_core.pydantic_serialization import SerializableModel

TransportOptionsT = TypeVar("TransportOptionsT", bound=SerializableModel)


class AgentTransport(ABC, Generic[TransportOptionsT]):
    """Abstract transport for Agent communication."""

    @classmethod
    @abstractmethod
    def build(cls, options: TransportOptionsT) -> ContextManager[Self]:
        """Build a transport from options.

        This is the main entry point for building a transport and managing its lifecycle.
        """

    @abstractmethod
    def send_request(self, messages: list[Any], agent_options: AgentOptions) -> None:
        """Send request to underlying agent via transport."""

    @abstractmethod
    def receive_messages(self) -> Iterator[dict[str, Any]]:
        """Receive messages from underlying agent via transport."""

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if transport is connected."""


class AgentSubprocessCLITransportOptions(SerializableModel):
    """Options for AgentSubprocessCLITransport."""

    cmd: Sequence[str]
    cwd: str | Path | None = None
    extra_env_vars: dict[str, str] | None = None


class AgentSubprocessCLITransport(AgentTransport[AgentSubprocessCLITransportOptions]):
    """Subprocess transport using Coding Agent via a CLI."""

    def __init__(
        self,
        popen: subprocess.Popen[str],
    ) -> None:
        self._process = popen
        self._stdin_stream = popen.stdin
        self._stdout_stream = popen.stdout
        self._stderr_stream = popen.stderr

    @classmethod
    @contextmanager
    def build(cls, options: AgentSubprocessCLITransportOptions) -> Generator[Self, None, None]:
        extra_env_vars = options.extra_env_vars or {}
        try:
            popen = subprocess.Popen(
                options.cmd,
                stdin=PIPE,
                stdout=PIPE,
                stderr=PIPE,
                cwd=options.cwd,
                env={**os.environ, **extra_env_vars},
                # ensure output is line buffered
                bufsize=1,
                text=True,
                encoding="utf-8",
            )
        except FileNotFoundError as e:
            raise AgentCLINotFoundError(f"Agent CLI not found for: cmd={options.cmd}") from e
        except Exception as e:
            raise AgentCLIConnectionError(f"Failed to start Agent CLI via cmd={options.cmd}: {e}") from e

        try:
            yield cls(popen)
        finally:
            # Make sure to terminate the process if it is still running, and clean up the streams
            if popen.poll() is None:
                try:
                    popen.terminate()
                    popen.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    popen.kill()
                    popen.wait(timeout=5.0)
            popen.stdout and popen.stdout.close()
            popen.stderr and popen.stderr.close()
            popen.stdin and popen.stdin.close()

    def send_request(self, messages: Iterable[dict[str, Any] | str], agent_options: AgentOptions) -> None:
        process = self._process
        stdin_stream = self._stdin_stream
        if not process or not stdin_stream:
            raise AgentCLIConnectionError("Not connected")

        try:
            for message in messages:
                stdin_stream.write(json.dumps(message) + "\n")
                stdin_stream.flush()
        except BrokenPipeError:
            pass

    def _read_stderr(self, output_buffer: list[str]) -> None:
        """Read stderr in background."""
        stderr_stream = self._stderr_stream
        if stderr_stream:
            try:
                for line in stderr_stream:
                    output_buffer.append(line.strip())
            except subprocess.SubprocessError:
                pass

    def receive_messages(self) -> Iterator[dict[str, Any]]:
        process = self._process
        stdout_stream = self._stdout_stream
        if not process or not stdout_stream:
            raise AgentCLIConnectionError("Not connected")

        stderr_lines: list[str] = []
        stderr_read_thread = threading.Thread(target=self._read_stderr, args=(stderr_lines,))
        stderr_read_thread.start()

        try:
            for line in stdout_stream:
                line_str = line.strip()
                if not line_str:
                    continue

                try:
                    data = json.loads(line_str)
                    try:
                        yield data
                    except GeneratorExit:
                        # Handle generator cleanup gracefully
                        return
                except json.JSONDecodeError as e:
                    if line_str.startswith("{") or line_str.startswith("["):
                        raise SDKJSONDecodeError(line_str, e) from e
                    continue

        except (subprocess.SubprocessError, BrokenPipeError):
            pass

        stderr_read_thread.join(timeout=5.0)
        process.wait()
        if process.returncode is not None and process.returncode != 0:
            stderr_output = "\n".join(stderr_lines)
            raise AgentProcessError(
                "CLI process failed",
                exit_code=process.returncode,
                stderr=stderr_output,
            )

    def is_connected(self) -> bool:
        process = self._process
        return process is not None and process.returncode is None
