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
                logger.debug("git apply failed, using fallback diff parser")
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
        is_rename = a_path != b_path

        hunks = _parse_hunks(section)

        if is_new:
            new_lines: list[str] = []
            for _, _, additions in hunks:
                new_lines.extend(additions)
            target = Path(temp_dir) / b_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("\n".join(new_lines) + "\n" if new_lines else "")
        elif hunks:
            base_text = _get_base_text(a_path, temp_dir, base_contents)
            base_lines = base_text.splitlines() if base_text else []
            result_lines = _apply_hunks_to_lines(base_lines, hunks)
            target = Path(temp_dir) / b_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("\n".join(result_lines) + "\n" if result_lines else "")
        elif is_rename:
            base_bytes = base_contents.get(a_path)
            target = Path(temp_dir) / b_path
            target.parent.mkdir(parents=True, exist_ok=True)
            if base_bytes is not None and isinstance(base_bytes, bytes):
                target.write_bytes(base_bytes)
            elif (Path(temp_dir) / a_path).exists():
                target.write_bytes((Path(temp_dir) / a_path).read_bytes())

        if is_rename:
            old_target = Path(temp_dir) / a_path
            if old_target.exists():
                old_target.unlink()


def _get_base_text(path: str, temp_dir: str, base_contents: InMemoryFileSystem) -> str:
    base_bytes = base_contents.get(path)
    if base_bytes is not None and isinstance(base_bytes, bytes):
        try:
            return base_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return ""
    on_disk = Path(temp_dir) / path
    if on_disk.exists():
        return on_disk.read_text()
    return ""


def _parse_hunks(section: str) -> list[tuple[int, int, list[str]]]:
    hunks: list[tuple[int, int, list[str]]] = []
    hunk_header_re = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
    current_start = 0
    current_count = 0
    new_lines: list[str] = []

    lines = section.split("\n")
    i = 0
    while i < len(lines):
        m = hunk_header_re.match(lines[i])
        if m:
            if current_start or new_lines:
                hunks.append((current_start, current_count, new_lines))
            current_start = int(m.group(1))
            current_count = int(m.group(2)) if m.group(2) else 1
            new_lines = []
            i += 1
            while i < len(lines):
                line = lines[i]
                if line.startswith("@@") or line.startswith("diff --git"):
                    break
                if line.startswith("+"):
                    new_lines.append(line[1:])
                elif line.startswith(" "):
                    new_lines.append(line[1:])
                elif line.startswith("-"):
                    pass
                elif line.startswith("\\"):
                    pass
                else:
                    break
                i += 1
            continue
        i += 1

    if current_start or new_lines:
        hunks.append((current_start, current_count, new_lines))

    return hunks


def _apply_hunks_to_lines(base_lines: list[str], hunks: list[tuple[int, int, list[str]]]) -> list[str]:
    result = list(base_lines)
    offset = 0
    for start, count, new_lines in hunks:
        idx = start - 1 + offset
        end_idx = idx + count
        result[idx:end_idx] = new_lines
        offset += len(new_lines) - count
    return result


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
