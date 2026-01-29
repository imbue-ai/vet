import asyncio
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator
from typing import Generator

import pygit2
from loguru import logger
from pygit2.enums import ObjectType
from pygit2.repository import Repository

from imbue_core.async_utils import make_async
from imbue_core.git import LocalGitRepo
from imbue_tools.repo_utils.diff_utils import apply_diffs_to_files
from imbue_tools.repo_utils.file_system import FileContents
from imbue_tools.repo_utils.file_system import InMemoryFileSystem
from imbue_tools.repo_utils.file_system import SymlinkContents


class RepoContextManagerError(Exception):
    pass


class RepoContextManager:
    """A manager for handling retrieval of files, etc from the repo."""

    def __init__(self, repo_path: Path, project_name: str) -> None:
        self.project_name = project_name
        self.repo_path = repo_path
        self._repo = Repository(path=str(repo_path))

        # We need the sync lock due to pygit2 being synchronous.
        # It is mostly used for the blob data cache, but also for the repo contents by git hash cache.
        self._lock = threading.Lock()
        # We need the async lock for tests TODO: we can probably remove this
        self._local_repo_async_lock: asyncio.Lock = asyncio.Lock()

    @classmethod
    def build(cls, repo_path: Path) -> "RepoContextManager":
        try:
            # make sure we are in a git repo
            Repository(path=str(repo_path))
        except pygit2.GitError as e:
            raise RepoContextManagerError(
                f"Failed to initialize git repo at {repo_path}"
            ) from e

        repo_context_manager = cls(repo_path=repo_path, project_name=repo_path.name)
        return repo_context_manager

    async def get_full_repo_contents_at_repo_state(
        self, git_hash: str, diff: str
    ) -> InMemoryFileSystem:
        final_contents = await self.get_full_repo_contents_at_commit(git_hash)
        final_contents = await apply_diffs_to_files(final_contents, (diff,))
        return final_contents

    def get_full_repo_contents_at_commit_sync(
        self, git_hash: str
    ) -> InMemoryFileSystem:
        # NOTE: most of the time we want to get the contents at a repo state, not a git hash.
        #   Call get_full_repo_contents_at_repo_state instead in that case.
        with self._lock:
            start_time = time.perf_counter()

            # Assert against use of HEAD specifically because there could be some existing code
            # that uses it, and we want to catch that. It would fail below as well with a KeyError,
            # but this assert makes the exception message more explicit.
            assert (
                git_hash != "HEAD"
            ), "Only proper commit hashes are supported, not HEAD"
            commit = self._repo[git_hash]
            assert isinstance(
                commit, pygit2.Commit
            ), f"Expected a pygit2.Commit, got {type(commit)}"

            full_repo_contents = self._read_blobs_from_commit(commit)

            end_time = time.perf_counter()
            logger.debug(
                "Loaded full repo contents for git hash {git_hash} in {duration:.2f} seconds",
                git_hash=git_hash,
                duration=end_time - start_time,
            )
            return full_repo_contents

    @make_async
    def get_full_repo_contents_at_commit(self, git_hash: str) -> InMemoryFileSystem:
        return self.get_full_repo_contents_at_commit_sync(git_hash)

    def _read_blobs_from_commit(self, commit: pygit2.Commit) -> InMemoryFileSystem:
        """Read all blobs in a given commit."""
        file_system_dict: dict[str, FileContents] = {}

        for path, blob in self._list_blobs_from_tree(
            commit.tree, skip_binary=False, skip_symlinks=False
        ):
            if blob.filemode == 0o120000:
                # Blob is a symbolic link. Its contents in git represent the target path.
                file_system_dict[path] = SymlinkContents(
                    target_path=blob.data.decode("utf-8")
                )
            else:
                file_system_dict[path] = blob.data
        return InMemoryFileSystem.build(file_system_dict)

    def _list_blobs_from_tree(
        self, tree: pygit2.Tree, skip_binary: bool, skip_symlinks: bool
    ) -> Generator[tuple[str, pygit2.Blob], None, None]:
        """Recursively list all blobs in a tree, including its subtrees."""
        assert self._lock.locked()
        for entry in tree:
            if entry.type == ObjectType.BLOB:
                assert isinstance(entry, pygit2.Blob)
                if skip_binary and entry.is_binary:
                    continue
                if skip_symlinks and entry.filemode == 0o120000:
                    continue

                blob_path = entry.name
                assert blob_path is not None
                yield blob_path, entry

            elif entry.type == ObjectType.TREE:
                assert isinstance(entry, pygit2.Tree)
                # Recurse into a subtree (folder)
                sub_tree = self._repo[entry.id]
                assert isinstance(sub_tree, pygit2.Tree)
                for sub_path, sub_blob in self._list_blobs_from_tree(
                    sub_tree, skip_binary=skip_binary, skip_symlinks=skip_symlinks
                ):
                    yield f"{entry.name}/{sub_path}", sub_blob

            elif entry.type == ObjectType.COMMIT:
                # A COMMIT object indicates a submodule, which we do not traverse for the time being.
                logger.info("Skipping submodule in repo context: {}", entry.name)

            else:
                raise ValueError(f"Unexpected entry type in git tree: {entry.type}")

    @asynccontextmanager
    async def tmp_repo_context(self) -> AsyncGenerator[LocalGitRepo, None]:
        """
        This function is only used in tests
        TODO: we can probably remove it
        """
        async with self._local_repo_async_lock:
            yield LocalGitRepo(self.repo_path)
