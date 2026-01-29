from enum import StrEnum
from functools import cached_property
from typing import Annotated
from typing import Any

from pydantic import Field
from pydantic import Tag
from pydantic import computed_field

from imbue_core.frozen_utils import FrozenDict
from imbue_core.pydantic_serialization import PydanticFrozenDictAnnotation
from imbue_core.pydantic_serialization import SerializableModel
from imbue_core.pydantic_serialization import build_discriminator

ResourceURL = str


class ConflictType(StrEnum):
    MERGE = "MERGE"
    REBASE = "REBASE"
    CHERRY_PICK = "CHERRY_PICK"
    APPLY = "APPLY"
    REVERT = "REVERT"
    BISECT = "BISECT"


class RepoOperation(SerializableModel):
    pass

    @computed_field
    @cached_property
    def is_empty(self) -> bool:
        """Whether this repo operation leaves the repo unchanged.

        Defaults to False. But should be overridden by subclasses as appropriate.
        """
        return False


class ConflictedRepoOperation(RepoOperation):
    object_type: str = "ConflictedRepoOperation"

    blob_content_by_hash: Annotated[FrozenDict[str, bytes], PydanticFrozenDictAnnotation]
    index_content: bytes
    modified_file_contents_by_path: Annotated[FrozenDict[str, bytes], PydanticFrozenDictAnnotation]
    conflict_type: ConflictType
    special_git_file_contents_by_path: Annotated[FrozenDict[str, bytes], PydanticFrozenDictAnnotation]


class CleanRepoOperation(RepoOperation):
    """
    A clean repo operation is a repo operation that has no conflicts.

    It is a contains the staged diff, the unstaged diff, and the combination of the previous two.
    """

    object_type: str = "CleanRepoOperation"
    combined_diff: str
    staged_diff: str = ""
    unstaged_diff: str = ""

    # FIXME: this is now doing validation -- should be converted to the pydantic way of doing this!
    def model_post_init(self, __context: Any) -> None:
        super().model_post_init(__context)
        if self.combined_diff.strip() != "":
            assert (
                self.staged_diff.strip() != "" or self.unstaged_diff.strip() != ""
            ), "combined diff is not empty, so staged and unstaged diffs must be non-empty"

    @computed_field
    @cached_property
    def is_empty(self) -> bool:
        return self.combined_diff.strip() == ""


class RepoState(SerializableModel):
    git_hash: str
    repo_operation: (
        Annotated[CleanRepoOperation, Tag("CleanRepoOperation")]
        | Annotated[ConflictedRepoOperation, Tag("ConflictedRepoOperation")]
    ) = Field(discriminator=build_discriminator())

    @computed_field
    @cached_property
    def is_conflicted(self) -> bool:
        return isinstance(self.repo_operation, ConflictedRepoOperation)

    @computed_field
    @cached_property
    def has_operations(self) -> bool:
        repo_operation = self.repo_operation
        return isinstance(repo_operation, ConflictedRepoOperation) or repo_operation.combined_diff.strip() != ""

    @computed_field
    @cached_property
    def type_name(self) -> str:
        return self.__class__.__name__

    def build_with_new_commit(self, git_hash: str) -> "RepoState":
        return RepoState(git_hash=git_hash, repo_operation=self.repo_operation)


GIT_FILE_PATH_NAMES_BY_CONFLICT_TYPE: dict[ConflictType, tuple[str, ...]] = {
    ConflictType.MERGE: ("MERGE_HEAD", "AUTO_MERGE", "MERGE_MSG", "MERGE_MODE"),
    ConflictType.REBASE: ("REBASE_HEAD",),
    ConflictType.CHERRY_PICK: ("CHERRY_PICK_HEAD",),
    ConflictType.APPLY: (),
    ConflictType.REVERT: ("REVERT_HEAD",),
}
