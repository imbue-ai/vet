import abc
import datetime
from enum import auto
from typing import Annotated
from typing import Self

from pydantic import AnyUrl
from pydantic import BaseModel
from pydantic import Tag

from imbue_core.agents.data_types.ids import ObjectID
from imbue_core.pydantic_serialization import build_discriminator
from imbue_core.upper_case_str_enum import UpperCaseStrEnum

# Payload types
#
# These are the concrete types that are arranged into a tree structure to represent progress.
# That tree is serialized and sent over the websocket to the frontend.


class ProgressID(ObjectID):
    tag: str = "progress"


class OperationState(UpperCaseStrEnum):
    """State of a long-running operation.

    Intended to be reused across different operation types.
    """

    NOT_STARTED = auto()
    IN_PROGRESS = auto()
    COMPLETED = auto()
    FAILED = auto()


class ProgressModel(abc.ABC, BaseModel):
    object_type: str = "ProgressModel"

    progress_id: ProgressID
    state: OperationState
    latest_update_time: datetime.datetime


class DownloadProgress(ProgressModel):
    """Progress information for a file download."""

    object_type: str = "DownloadProgress"

    url: AnyUrl
    description: str | None
    total_bytes: int | None = None
    bytes_per_second: float | None = None
    remaining_seconds: float | None = None
    bytes_downloaded: int = 0
    failure_explanation: str | None = None


class SubprocessProgress(ProgressModel):
    """Progress information for a subprocess."""

    object_type: str = "SubprocessProgress"

    description: str | None = None

    # We hopefully don't expose any secrets in commands.
    # We might need some mechanism to scrub commands.
    #
    # I have _not_ included environment variables here, since those are basically guaranteed
    # to contain secrets and I want to keep the initial implementation relatively simple.
    command: str | None = None
    return_code: int | None = None
    failure_explanation: str | None = None


class MultiOperationProgress(ProgressModel):
    """Progress information for multiple operations."""

    object_type: str = "MultiOperationProgress"

    operations: list["ProgressTypes"]

    @classmethod
    def from_empty(cls) -> Self:
        return cls(
            progress_id=ProgressID(),
            operations=[],
            latest_update_time=datetime.datetime.now(),
            state=OperationState.NOT_STARTED,
        )


ProgressTypes = Annotated[
    Annotated[DownloadProgress, Tag("DownloadProgress")]
    | Annotated[SubprocessProgress, Tag("SubprocessProgress")]
    | Annotated[MultiOperationProgress, Tag("MultiOperationProgress")],
    build_discriminator(),
]


class BranchNameAndTaskTitleProgress(MultiOperationProgress):
    """Progress information for branch name generation operations."""

    generated_branch_name: str | None = None
    generated_task_title: str | None = None


class RootProgress(BaseModel):
    """Root progress information.

    This top-level progress object is serialized and sent to the frontend for ~every update.
    """

    snapshot_uncommitted_changes: MultiOperationProgress
    branch_name_and_task_title_generation: BranchNameAndTaskTitleProgress
    image_build: MultiOperationProgress
    container_setup: MultiOperationProgress
    agent_branch_checkout: MultiOperationProgress

    @classmethod
    def from_empty(cls) -> Self:
        return cls(
            snapshot_uncommitted_changes=MultiOperationProgress.from_empty(),
            branch_name_and_task_title_generation=BranchNameAndTaskTitleProgress.from_empty(),
            image_build=MultiOperationProgress.from_empty(),
            container_setup=MultiOperationProgress.from_empty(),
            agent_branch_checkout=MultiOperationProgress.from_empty(),
        )
