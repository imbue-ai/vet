"""
Progress tracking utilities.

These are placeholder base classes and common utilities that have minimal dependencies.

For now, we are working on plumbing these into various parts of the system. We will
expand these interfaces and add "real" implementations as we go.
"""

import abc
from contextlib import contextmanager
from typing import Callable
from typing import Generator
from typing import Generic
from typing import Sequence
from typing import TypeVar

from pydantic import AnyUrl


class StartFinishHandle(abc.ABC):
    """A handle that supports start/finish reporting."""

    @abc.abstractmethod
    def on_start(self) -> None:
        """Called when the operation is started."""
        ...

    @abc.abstractmethod
    def finish(self) -> None:
        """Report that the operation has finished successfully."""
        ...

    @abc.abstractmethod
    def report_failure(self, explanation: str) -> None:
        """Report that the operation has failed."""
        ...


StartFinishHandleT = TypeVar("StartFinishHandleT", bound=StartFinishHandle, covariant=True)


class UnstartedHandle(Generic[StartFinishHandleT]):
    def __init__(self, handle: StartFinishHandleT) -> None:
        self.handle = handle

    def start(self) -> StartFinishHandleT:
        self.handle.on_start()
        return self.handle


def get_unstarted(handle_factory: Callable[[], StartFinishHandleT]) -> UnstartedHandle[StartFinishHandleT]:
    return UnstartedHandle(handle_factory())


@contextmanager
def start_finish_context(
    unstarted_handle: UnstartedHandle[StartFinishHandleT],
) -> Generator[StartFinishHandleT, None, None]:
    """Context manager to facilitate generic start/finish reporting.

    Example usage:
    with start_finish_context(handle.track_subprocess("Pulling recent changes")) as subprocess_handle:
        # do work with subprocess_handle
    """
    handle = unstarted_handle.start()
    try:
        yield handle
    except Exception as e:
        handle.report_failure(str(e))
        raise
    else:
        handle.finish()


T = TypeVar("T")


class ProgressHandle(StartFinishHandle):
    """Handle for overall progress of multiple operations."""

    def on_start(self) -> None: ...

    def finish(self) -> None: ...

    def report_failure(self, explanation: str) -> None: ...

    def track_download(self, url: AnyUrl, description: str | None = None) -> UnstartedHandle["DownloadHandle"]:
        """Get a handle for tracking a file download."""
        return get_unstarted(DownloadHandle)

    def track_subprocess(self, description: str | None = None) -> UnstartedHandle["SubprocessHandle"]:
        """Get a handle for tracking a subprocess."""
        return get_unstarted(SubprocessHandle)

    def track_subtask(self, description: str | None = None) -> UnstartedHandle["ProgressHandle"]:
        return get_unstarted(ProgressHandle)


class DownloadHandle(StartFinishHandle):
    """Interface for file download progress."""

    def on_start(self) -> None: ...

    def finish(self) -> None: ...

    def report_failure(self, explanation: str) -> None: ...

    def report_size(self, total_bytes: int) -> None:
        """Report that we have discovered the total size of the download."""
        pass

    def report_progress(self, total_bytes_downloaded: int) -> None:
        """Report progress of the download.

        Args:
            total_bytes_downloaded: The _total_ number of bytes downloaded so far.
        """
        pass

    def report_failed_attempt(self, explanation: str) -> None:
        """Report that an attempt to download has failed, but more attempts may follow."""
        pass


class SubprocessHandle(StartFinishHandle):
    """Handle for subprocess progress."""

    def on_start(self) -> None: ...

    def finish(self) -> None: ...

    def report_failure(self, explanation: str) -> None: ...

    def report_command(self, command: str | Sequence[str]) -> None:
        """Report the command being run."""
        pass

    def report_output_line(self, line: str, is_stderr: bool) -> None:
        """Report a line of output from the subprocess."""
        pass

    def report_return_code(self, return_code: int) -> None:
        """Report the return code of the subprocess."""
        pass


class BranchNameAndTaskTitleProgressHandle(ProgressHandle):
    """Progress handle for branch name generation operations."""

    def on_start(self) -> None: ...

    def finish(self) -> None: ...

    def report_failure(self, explanation: str) -> None: ...

    def report_generated_branch_name(self, branch_name: str, task_title: str) -> None:
        """Report the generated branch name and task title."""
        pass


class RootProgressHandle:
    """Root progress handle that can create scoped progress handles (e.g. on a per-task basis)."""

    def track_snapshot_uncommitted_changes(self) -> UnstartedHandle[ProgressHandle]:
        """Get a progress handle for tracking uncommitted changes snapshotting."""
        return get_unstarted(ProgressHandle)

    def track_branch_name_and_task_title_generation(
        self, source_branch: str
    ) -> UnstartedHandle[BranchNameAndTaskTitleProgressHandle]:
        """Get a progress handle for tracking branch name generation."""
        return get_unstarted(BranchNameAndTaskTitleProgressHandle)

    def track_image_build(self) -> UnstartedHandle[ProgressHandle]:
        """Get a progress handle for tracking image building."""
        return get_unstarted(ProgressHandle)

    def track_container_setup(self, container_name: str) -> UnstartedHandle[ProgressHandle]:
        """Get a progress handle for tracking container setup."""
        return get_unstarted(ProgressHandle)

    def track_agent_branch_checkout(self) -> UnstartedHandle[ProgressHandle]:
        """Get a progress handle for tracking agent branch checkout."""
        return get_unstarted(ProgressHandle)
