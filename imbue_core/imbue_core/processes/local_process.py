"""
Defines 3 main functions for interacting with processes:
- run_blocking: Runs a command and waits for it to complete, returning all output at once.
- run_streaming: Runs a command and waits for it to complete, calling a callback for each line of output as it's produced.
- run_background: Starts a command in the background, returning a RunningProcess object to manage it and access output via a queue.

Avoid using the builtin subprocess module directly; use these functions instead for consistent behavior.

Examples of errors avoided by these wrappers:
- Blocking indefinitely on process output if the output buffer fills up.
- Inconsistent handling of stdout/stderr output.
- Difficulty interrupting long-running processes cleanly.
- Processing streaming output in real-time.
"""

from __future__ import annotations

import contextvars
from pathlib import Path
from queue import Empty
from queue import Queue
from subprocess import TimeoutExpired
from threading import Event
from typing import Callable
from typing import Iterator
from typing import Mapping
from typing import Sequence
from typing import TypeVar

from imbue_core.event_utils import MutableEvent
from imbue_core.processes.errors import EnvironmentStoppedError
from imbue_core.subprocess_utils import FinishedProcess
from imbue_core.subprocess_utils import ProcessError
from imbue_core.subprocess_utils import ProcessSetupError
from imbue_core.subprocess_utils import run_local_command_modern_version
from imbue_core.thread_utils import ObservableThread


def run_blocking(
    command: Sequence[str],
    timeout: float | None = None,
    is_checked: bool = True,
    is_output_traced: bool = False,
    trace_on_line_callback: Callable[[str, bool], None] | None = None,
    cwd: Path | None = None,
    trace_log_context: Mapping[str, object] | None = None,
    shutdown_event: MutableEvent | None = None,
    shutdown_timeout_sec: float = 30.0,
    poll_time: float = 0.01,
    env: Mapping[str, str] | None = None,
) -> FinishedProcess:
    """
    Run a subprocess command in a blocking manner with consistent output handling.

    This function wraps subprocess execution to provide a single, interruptible function call
    similar to subprocess.run, but with added features for consistent output handling and
    interruption support. While the output streaming capability is more relevant for
    run_streaming and run_background, this function provides the foundation for consistent
    process execution across the codebase.

    Args:
        command: The command to execute as a sequence of strings (e.g., ['echo', 'hello'])
        timeout: Maximum time in seconds to wait for the command to complete
        is_checked: If True, raises an exception if the command returns non-zero exit code
        is_output_traced: If True, enables output tracing/logging. Off by default.
        trace_on_line_callback: A callback which will be called once per line that is called
        cwd: Working directory for the command execution. MUST be passed if is_output_traced
        trace_log_context: Additional context to include in trace logs
        shutdown_event: Event that can be used to interrupt the command execution
        shutdown_timeout_sec: Timeout in seconds when shutting down via shutdown_event
        poll_time: Time in seconds to wait between polls to check if the process is finished.
        env: Environment variables to pass to subprocess.Popen

    Returns:
        FinishedProcess: Object containing returncode, stdout, stderr, and command info

    Raises:
        ProcessError: If is_checked=True and the command returns non-zero exit code
        ProcessTimeoutError: If the command exceeds the specified timeout
        ProcessSetupError: If the command was never able to start executing
    """
    return run_local_command_modern_version(
        command=command,
        is_checked=is_checked,
        timeout=timeout,
        trace_output=is_output_traced,
        trace_on_line_callback=trace_on_line_callback,
        cwd=cwd,
        trace_log_context=trace_log_context,
        shutdown_event=shutdown_event,
        shutdown_timeout_sec=shutdown_timeout_sec,
        poll_time=poll_time,
        env=env,
    )


def run_streaming(
    command: Sequence[str],
    on_output: Callable[[str, bool], None],
    is_checked: bool = True,
    timeout: float | None = None,
    cwd: Path | None = None,
    trace_log_context: Mapping[str, object] | None = None,
    shutdown_event: MutableEvent | None = None,
    shutdown_timeout_sec: float = 30.0,
    env: Mapping[str, str] | None = None,
) -> FinishedProcess:
    """
    Run a subprocess command in a blocking manner with streaming output via callbacks.

    This function wraps subprocess execution to provide real-time output streaming. Unlike
    run_blocking which collects all output, this function calls the provided callback for
    each complete line of output as it's produced. A complete line is one that ends with
    a newline character. Partial lines (without trailing newline) are not passed to the
    callback but are still captured in the returned FinishedProcess.

    Args:
        command: The command to execute as a sequence of strings (e.g., ['echo', 'hello'])
        on_output: Callback function called for each complete line of output. Receives (line, is_stdout)
                   where line includes the newline character and is_stdout is True for stdout, False for stderr.
                   Note: Lines without trailing newlines are not passed to this callback
        is_checked: If True, raises an exception if the command returns non-zero exit code
        timeout: Maximum time in seconds to wait for the command to complete (None for no timeout)
        cwd: Working directory for the command execution
        trace_log_context: Additional context to include in trace logs
        shutdown_event: Event that can be used to interrupt the command execution
        shutdown_timeout_sec: Timeout in seconds when shutting down via shutdown_event
        env: Environment variables to pass to subprocess.Popen

    Returns:
        FinishedProcess: Object containing returncode, stdout, stderr, and command info

    Raises:
        ProcessError: If is_checked=True and the command returns non-zero exit code
        ProcessTimeoutError: If the command exceeds the specified timeout
        ProcessSetupError: If the command was never able to start executing
    """
    return run_local_command_modern_version(
        command=command,
        is_checked=is_checked,
        timeout=timeout,
        # TODO: trace_output is redundant, we should determine its truthiness by presence of trace_on_line_callback
        trace_output=bool(on_output),
        cwd=cwd,
        trace_on_line_callback=on_output,
        trace_log_context=trace_log_context,
        shutdown_event=shutdown_event,
        shutdown_timeout_sec=shutdown_timeout_sec,
        env=env,
    )


class RunningProcess:
    def __init__(
        self,
        command: Sequence[str],
        output_queue: Queue[tuple[str, bool]] | None,
        shutdown_event: MutableEvent,
        is_checked: bool = False,
    ) -> None:
        self._command = command
        self._output_queue = output_queue
        self._shutdown_event = shutdown_event
        self._is_checked = is_checked
        self._completed_process: FinishedProcess | None = None
        self._thread: ObservableThread | None = None
        self._stdout_lines: list[str] = []
        self._stderr_lines: list[str] = []

    def read_stdout(self) -> str:
        return "".join(self._stdout_lines)

    def stream_stdout_and_stderr(self) -> Iterator[tuple[str, bool]]:
        """
        Iterator that yields lines from the process output queue.
        Each item is (line, is_stdout).
        Stops when the process stop_event is set.
        """
        output_queue = self.get_queue()

        while not self._shutdown_event.is_set():
            try:
                line, is_stdout = output_queue.get(timeout=0.1)
                yield line, is_stdout
            except Empty:
                if self.poll() is not None:
                    break

    def read_stderr(self) -> str:
        return "".join(self._stderr_lines)

    def get_queue(self) -> Queue[tuple[str, bool]]:
        assert self._output_queue is not None, "Output queue must be set to get the queue for RunningProcess"
        return self._output_queue

    @property
    def returncode(self) -> int | None:
        return self.poll()

    @property
    def is_checked(self) -> bool:
        return self._is_checked

    @property
    def command(self) -> Sequence[str]:
        """Human-readable command string."""
        return self._command

    def wait_and_read(self, timeout: float | None = None) -> tuple[str, str]:
        self.wait(timeout)
        return self.read_stdout(), self.read_stderr()

    def wait(self, timeout: float | None = None) -> int:
        thread = self._thread
        assert thread is not None, "Thread must be started before waiting"
        if thread.is_alive():
            thread.join(timeout)
        if thread.is_alive():
            stdout = self.read_stdout()
            stderr = self.read_stderr()
            # pyre-fixme[6]: presumably timeout must not be None to escape thread.join with the thread still alive, but pyre doesn't know this
            raise TimeoutExpired(self._command, timeout, stdout, stderr)
        result = self.poll()
        if result is None:
            raise ProcessSetupError(
                command=tuple(self._command),
                stdout="",
                stderr="Process exited before being started!",
                is_output_already_logged=True,
            )
        if self._is_checked:
            self.check()
        return result

    def check(self) -> None:
        if self.returncode is not None and self.returncode != 0:
            stdout, stderr = self.read_stdout(), self.read_stderr()
            raise ProcessError(tuple(self._command), stdout, stderr, self.returncode)

    def poll(self) -> int | None:
        thread = self._thread
        if thread is None or thread.native_id is None:
            # Not started yet.
            return None
        if self._completed_process is not None:
            return self._completed_process.returncode

        # if the thread has died, we need to return a fake exit code
        if not thread.is_alive():
            # ok, but double check if the process is done:
            if self._completed_process is not None:
                return self._completed_process.returncode
            # and if not, also see if there was an exception
            if thread.exception_raw is not None:
                thread.join()
            # fine, whatever, this died without an exception, that's pretty strange
            return 1007

        return None

    def is_finished(self) -> bool:
        try:
            return self.poll() is not None
        except ProcessSetupError:
            return True

    def terminate(self, force_kill_seconds: float = 5.0) -> None:
        self._shutdown_event.set()
        thread = self._thread
        assert thread is not None
        thread.join(timeout=force_kill_seconds)
        if thread.is_alive():
            stdout = self.read_stdout()
            stderr = self.read_stderr()
            raise TimeoutExpired(self._command, force_kill_seconds, stdout, stderr)

    def start(self, kwargs: dict) -> None:
        # Spawning a thread is an implementation detail of this class.
        # The caller should not have to worry about contextvars (e.g the loguru logging context).
        context = contextvars.copy_context()
        queue: Queue[BaseException | None] = Queue(maxsize=1)
        on_initialized = lambda maybe_exception: queue.put_nowait(maybe_exception)
        self._thread = ObservableThread(
            target=lambda: context.run(self.run, {**kwargs, "on_initialization_complete": on_initialized}),
            name=self._get_name(),
            silenced_exceptions=(ProcessError, EnvironmentStoppedError),
        )
        self._thread.start()
        maybe_initialization_exception = queue.get()
        if maybe_initialization_exception is not None:
            raise maybe_initialization_exception

    def _get_name(self) -> str:
        return f"RunningProcess: {' '.join(self._command)}"

    def run(self, kwargs: dict) -> None:
        self._completed_process = run_local_command_modern_version(**kwargs)

    def get_timed_out(self) -> bool:
        if self._completed_process is None:
            return False
        return self._completed_process.is_timed_out

    def on_line(self, line: str, is_stdout: bool) -> None:
        if is_stdout:
            self._stdout_lines.append(line)
        else:
            self._stderr_lines.append(line)
        # pyre-fixme[16]: pyre thinks _output_queue can be None
        self._output_queue.put((line, is_stdout))


ProcessClassType = TypeVar("ProcessClassType", bound=RunningProcess)


def run_background(
    command: Sequence[str],
    output_queue: Queue[tuple[str, bool]] | None = None,
    timeout: float | None = None,
    # is_checked is False by default for backwards compatibility
    is_checked: bool = False,
    cwd: Path | None = None,
    trace_log_context: Mapping[str, object] | None = None,
    shutdown_event: MutableEvent | None = None,
    shutdown_timeout_sec: float = 30.0,
    env: Mapping[str, str] | None = None,
    process_class: type[ProcessClassType] = RunningProcess,
    process_class_kwargs: Mapping[str, object] | None = None,
) -> ProcessClassType:
    """
    Run a subprocess command in a non-blocking manner with output handling.

    This function wraps subprocess execution to provide non-blocking process management
    with real-time output streaming via a queue. Unlike run_blocking and run_streaming,
    this function returns immediately with a RunningProcess object that allows the caller
    to either:
    - Access a queue to process output lines as they are produced
    - Wait for completion and read all output at once
    - Check process status, terminate it, or monitor return codes

    Args:
        command: The command to execute as a sequence of strings (e.g., ['echo', 'hello'])
        output_queue: Optional queue for receiving output as (line, is_stdout) tuples.
                      If not provided, a new queue is created. Each line includes newline.
        timeout: Maximum time in seconds for the command to complete (None for no timeout)
        is_checked: If True, creates a RunningProcess whose wait() method raises an error
                    if the command ends up returning a non-zero exit code.
        cwd: Working directory for the command execution
        trace_log_context: Additional context to include in trace logs
        shutdown_event: Event that can be used to interrupt the command execution
        shutdown_timeout_sec: Timeout in seconds when shutting down via shutdown_event

    Returns:
        RunningProcess
    """
    if output_queue is None:
        output_queue = Queue()
    true_shutdown_event = shutdown_event if shutdown_event is not None else Event()
    process = process_class(
        output_queue=output_queue,
        shutdown_event=true_shutdown_event,
        command=command,
        is_checked=is_checked,
        **(process_class_kwargs or {}),
    )
    process.start(
        kwargs=dict(
            command=command,
            is_checked=False,
            timeout=timeout,
            trace_output=bool(process.on_line),
            cwd=cwd,
            trace_on_line_callback=process.on_line,
            trace_log_context=trace_log_context,
            shutdown_event=true_shutdown_event,
            shutdown_timeout_sec=shutdown_timeout_sec,
            env=env,
        )
    )
    return process
