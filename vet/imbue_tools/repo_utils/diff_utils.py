import re
import subprocess
import tempfile
from pathlib import Path

import pygit2
from async_lru import alru_cache  # type: ignore[undefined-attribute]: pyre on modal has an issue with this
from loguru import logger

from vet.imbue_tools.repo_utils.errors import DiffApplicationError
from vet.imbue_tools.repo_utils.file_system import FileContents
from vet.imbue_tools.repo_utils.file_system import InMemoryFileSystem
from vet.imbue_tools.repo_utils.file_system import SymlinkContents
from vet.imbue_tools.repo_utils.file_system_utils import create_initial_placeholder_commit_for_dir
from vet.imbue_tools.repo_utils.file_system_utils import temporary_local_dir_from_in_memory_file_system


@alru_cache
async def apply_diffs_to_files(file_contents: InMemoryFileSystem, diff_strings: tuple[str, ...]) -> InMemoryFileSystem:
    # Have to do this wrapping and unwrapping into dicts to allow @alru_cache to work
    files_with_diffs = file_contents
    for diff_string in diff_strings:
        files_with_diffs = await _apply_diff_to_files(file_contents=files_with_diffs, diff_string=diff_string)
    return files_with_diffs


async def _apply_diff_to_files(file_contents: InMemoryFileSystem, diff_string: str) -> InMemoryFileSystem:
    if diff_string.strip() == "":
        return file_contents

    file_pattern = re.compile(r"^diff --git a/(.+?) b/(.+)$", re.MULTILINE)
    matches = file_pattern.findall(diff_string)

    relevant_file_contents_dict: dict[str, FileContents] = {}
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

            applied = False
            for apply_args in [
                ("git", "apply", "--verbose", patch_file_path),
                ("git", "apply", "--verbose", "--unidiff-zero", "--reject", patch_file_path),
            ]:
                try:
                    subprocess.run(
                        apply_args,
                        cwd=temp_repo_dir,
                        capture_output=True,
                        text=True,
                        timeout=10.0,
                        check=True,
                    )
                    applied = True
                    break
                except subprocess.CalledProcessError:
                    continue

            if not applied:
                _fallback_apply(diff_string, temp_repo_dir, file_contents)

        try:
            updated_file_contents = _read_file_contents_from_dir_without_git(temp_repo_dir)
        except Exception as e:
            raise DiffApplicationError from e

    combined_file_contents_dict = dict(updated_file_contents.files)
    for file_path, contents in file_contents.files.items():
        if file_path not in relevant_file_contents_dict:
            combined_file_contents_dict[file_path] = contents

    deleted_paths = _parse_deleted_paths(diff_string)
    renamed_from = {m[0] for m in matches if m[0] != m[1]}
    for path in deleted_paths | renamed_from:
        combined_file_contents_dict.pop(path, None)

    return InMemoryFileSystem.build(combined_file_contents_dict)


def _fallback_apply(diff_string: str, temp_dir: str, base_contents: InMemoryFileSystem) -> None:
    for section in re.split(r"(?=^diff --git )", diff_string, flags=re.MULTILINE):
        section = section.strip()
        if not section:
            continue

        header_match = re.match(r"^diff --git a/(.+?) b/(.+)$", section, re.MULTILINE)
        if not header_match:
            continue

        a_path, b_path = header_match.group(1), header_match.group(2)

        if re.search(r"^deleted file mode", section, re.MULTILINE):
            target = Path(temp_dir) / b_path
            if target.exists():
                target.unlink()
            continue

        is_new = bool(re.search(r"^new file mode", section, re.MULTILINE))
        is_rename = bool(re.search(r"^rename from ", section, re.MULTILINE))

        added_lines = []
        in_hunk = False
        for line in section.split("\n"):
            if line.startswith("@@"):
                in_hunk = True
                continue
            if in_hunk:
                if line.startswith("+"):
                    added_lines.append(line[1:])
                elif line.startswith(" "):
                    added_lines.append(line[1:])
                elif line.startswith("-"):
                    pass
                elif line.startswith("\\"):
                    pass
                else:
                    in_hunk = False

        if is_new or added_lines:
            target = Path(temp_dir) / b_path
            target.parent.mkdir(parents=True, exist_ok=True)
            if added_lines:
                target.write_text("\n".join(added_lines) + ("\n" if added_lines else ""))
            elif is_new:
                target.touch()

        if is_rename:
            old_target = Path(temp_dir) / a_path
            if old_target.exists():
                old_target.unlink()


def _parse_deleted_paths(diff_string: str) -> set[str]:
    deleted = set()
    for section in re.split(r"(?=^diff --git )", diff_string, flags=re.MULTILINE):
        if re.search(r"^deleted file mode", section, re.MULTILINE):
            header_match = re.match(r"^diff --git a/(.+?) b/(.+)$", section, re.MULTILINE)
            if header_match:
                deleted.add(header_match.group(2))
    return deleted


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
