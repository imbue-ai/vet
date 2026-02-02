import asyncio
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator
from typing import cast

import anyio
import pygit2
from loguru import logger

from vet.imbue_tools.repo_utils.file_system import FileContents
from vet.imbue_tools.repo_utils.file_system import InMemoryFileSystem
from vet.imbue_tools.repo_utils.file_system import SymlinkContents


async def write_file_contents_to_dir(file_contents: InMemoryFileSystem, dir_path_str: str) -> None:
    dir_path = Path(dir_path_str)
    tasks = [
        asyncio.create_task(_write_single_file_to_dir(dir_path / file_path, content))
        for file_path, content in file_contents.files.items()
    ]
    await asyncio.gather(*tasks)


async def _write_single_file_to_dir(full_path: Path, content: FileContents) -> None:
    await anyio.to_thread.run_sync(_write_file_sync, full_path, content)


def _write_file_sync(full_path: Path, content: FileContents) -> None:
    full_path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        full_path.write_bytes(content)
    elif isinstance(content, SymlinkContents):
        full_path.symlink_to(content.target_path)
    else:
        logger.error(
            "Tried to write contents that were neither bytes nor SymlinkContents: {content}",
            content=content,
        )


@asynccontextmanager
async def temporary_local_dir_from_in_memory_file_system(
    file_contents: InMemoryFileSystem,
) -> AsyncGenerator[str, None]:
    with tempfile.TemporaryDirectory() as temp_dir:
        await write_file_contents_to_dir(file_contents, temp_dir)
        yield temp_dir


def create_initial_placeholder_commit_for_dir(repo: pygit2.Repository) -> pygit2.Commit:
    # pyre-ignore[16]: pyre doesn't understand the inheritance of Repository from BaseRepository
    repo_index = repo.index
    repo_index.add_all()
    repo_index.write()
    tree = repo_index.write_tree()
    signature = pygit2.Signature("placeholder", "placeholder@example.com")

    commit_oid = repo.create_commit(
        "refs/heads/master",
        signature,
        signature,
        "placeholder commit for diff utils",
        tree,
        [],
    )
    # pyre-ignore[16]: pyre doesn't understand the inheritance of Repository from BaseRepository
    commit = repo.get(commit_oid)
    return cast(pygit2.Commit, commit)
