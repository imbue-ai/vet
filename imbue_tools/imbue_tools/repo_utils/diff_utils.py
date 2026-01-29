import re
import subprocess
import tempfile
from pathlib import Path

import pygit2
from async_lru import alru_cache  # type: ignore[undefined-attribute]: pyre on modal has an issue with this
from loguru import logger

from imbue_tools.repo_utils.errors import DiffApplicationError
from imbue_tools.repo_utils.errors import DiffCalculationError
from imbue_tools.repo_utils.file_system import FileContents
from imbue_tools.repo_utils.file_system import InMemoryFileSystem
from imbue_tools.repo_utils.file_system import SymlinkContents
from imbue_tools.repo_utils.file_system_utils import (
    create_initial_placeholder_commit_for_dir,
)
from imbue_tools.repo_utils.file_system_utils import (
    temporary_local_dir_from_in_memory_file_system,
)
from imbue_tools.repo_utils.file_system_utils import write_file_contents_to_dir


class NonZeroReturncodeError(Exception):
    pass


async def get_diff_between_files(
    old_file_contents: InMemoryFileSystem, new_file_contents: InMemoryFileSystem
) -> str:
    with (
        tempfile.TemporaryDirectory() as old_repo_dir,
        tempfile.TemporaryDirectory() as new_repo_dir,
    ):
        # Get all changed file contents to prevent writing more than necessary
        changed_old_file_contents_dict = {}
        changed_new_file_contents_dict = {}
        old_file_contents_dict = old_file_contents.files
        new_file_contents_dict = new_file_contents.files
        for file_path in old_file_contents_dict.keys() | new_file_contents_dict.keys():
            if file_path not in old_file_contents_dict:
                changed_new_file_contents_dict[file_path] = new_file_contents_dict[
                    file_path
                ]
            elif file_path not in new_file_contents_dict:
                changed_old_file_contents_dict[file_path] = old_file_contents_dict[
                    file_path
                ]
            elif old_file_contents_dict[file_path] != new_file_contents_dict[file_path]:
                changed_old_file_contents_dict[file_path] = old_file_contents_dict[
                    file_path
                ]
                changed_new_file_contents_dict[file_path] = new_file_contents_dict[
                    file_path
                ]

        changed_old_file_contents = InMemoryFileSystem.build(
            changed_old_file_contents_dict
        )
        changed_new_file_contents = InMemoryFileSystem.build(
            changed_new_file_contents_dict
        )

        await write_file_contents_to_dir(changed_old_file_contents, old_repo_dir)
        await write_file_contents_to_dir(changed_new_file_contents, new_repo_dir)

        try:
            result = subprocess.run(
                (
                    "git",
                    "diff",
                    "--no-index",
                    "--relative",
                    "--full-index",
                    "--binary",
                    old_repo_dir,
                    new_repo_dir,
                ),
                capture_output=True,
                text=True,
                timeout=10.0,
            )
            if result.returncode == 0 or result.returncode == 1:
                diff = result.stdout
            else:
                raise NonZeroReturncodeError(
                    f"git diff process returned with non-zero returncode {result.returncode}"
                )
        except Exception as e:
            raise DiffCalculationError from e

        diff = diff.replace(old_repo_dir, "")
        diff = diff.replace(new_repo_dir, "")

        return diff


@alru_cache
async def apply_diffs_to_files(
    file_contents: InMemoryFileSystem, diff_strings: tuple[str, ...]
) -> InMemoryFileSystem:
    # Have to do this wrapping and unwrapping into dicts to allow @alru_cache to work
    files_with_diffs = file_contents
    for diff_string in diff_strings:
        files_with_diffs = await _apply_diff_to_files(
            file_contents=files_with_diffs, diff_string=diff_string
        )
    return files_with_diffs


async def _apply_diff_to_files(
    file_contents: InMemoryFileSystem, diff_string: str
) -> InMemoryFileSystem:
    if diff_string.strip() == "":
        return file_contents

    file_pattern = re.compile(r"^diff --git a/(.+?) b/(.+)$", re.MULTILINE)
    matches = file_pattern.findall(diff_string)

    relevant_file_contents_dict = {}
    for match in matches:
        assert len(match) == 2
        for file_path in match:
            contents = file_contents.get(file_path, None)
            if contents is not None:
                relevant_file_contents_dict[file_path] = contents

    async with temporary_local_dir_from_in_memory_file_system(
        InMemoryFileSystem.build(relevant_file_contents_dict)
    ) as temp_repo_dir:
        repo = pygit2.init_repository(temp_repo_dir, bare=False)
        create_initial_placeholder_commit_for_dir(repo)

        with tempfile.NamedTemporaryFile(delete=False) as temp_patch_file:
            temp_patch_file.write(diff_string.encode("utf-8"))
            temp_patch_file.flush()
            patch_file_path = temp_patch_file.name

            try:
                result = subprocess.run(
                    ("git", "apply", "--verbose", patch_file_path),
                    cwd=temp_repo_dir,
                    capture_output=True,
                    text=True,
                    timeout=10.0,
                    check=True,
                )
            except Exception as e:
                logger.trace("Unable to apply patch: {error}", error=e)
                raise DiffApplicationError from e

        try:
            updated_file_contents = _read_file_contents_from_dir_without_git(
                temp_repo_dir
            )
        except Exception as e:
            raise DiffApplicationError from e

    combined_file_contents_dict = dict(updated_file_contents.files)
    for file_path, contents in file_contents.files.items():
        if file_path not in relevant_file_contents_dict:
            combined_file_contents_dict[file_path] = contents

    return InMemoryFileSystem.build(combined_file_contents_dict)


def _read_file_contents_from_dir_without_git(dir_path_str: str) -> InMemoryFileSystem:
    file_system_dict: dict[str, FileContents] = {}
    for file_path in Path(dir_path_str).rglob("*"):
        if ".git" in file_path.parts:
            continue
        if file_path.is_symlink():
            relative_path = str(file_path.relative_to(dir_path_str))
            target_path = str(file_path.readlink())
            file_system_dict[relative_path] = SymlinkContents(target_path=target_path)
        elif file_path.is_file():
            relative_path = str(file_path.relative_to(dir_path_str))
            with open(file_path, "rb") as file:
                file_system_dict[relative_path] = file.read()
    return InMemoryFileSystem.build(file_system_dict)
