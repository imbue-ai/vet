from pathlib import Path
from typing import Iterable

from imbue_tools.repo_utils.python_imports import QualifiedName


def escape_prompt_markers(text: str) -> str:
    markers = [
        "[ROLE=ASSISTANT]",
        "[ROLE=USER]",
        "[ROLE=USER_CACHED]",
        "[ROLE=SYSTEM]",
        "[ROLE=SYSTEM_CACHED]",
        "[ROLE=HUMAN]",
    ]
    for marker in markers:
        text = text.replace(marker, f"[{marker}]")
    return text


def escape_all_jinja_variables(text: str) -> str:
    return "{% raw %}" + text + "{% endraw %}"


def does_relative_path_match_target_path_suffix(
    target_path: Path, relative_file_path: Path
) -> bool:
    """
    Checks if the parts of a relative path match the suffix of a target path.
    """
    possible_parts = relative_file_path.parts
    target_parts = target_path.parts

    if len(possible_parts) > len(target_parts):
        return False

    for i in range(1, len(possible_parts) + 1):
        if possible_parts[-i] != target_parts[-i]:
            return False
    return True


def maybe_get_file_path_from_qualified_name(
    qualified_name: QualifiedName, all_file_paths: Iterable[Path]
) -> Path | None:
    """
    Tries to find the file path that corresponds to qualified name. This requires the qualified name to be a file in the repo.
    """
    possible_relative_file_path = qualified_name.to_path()
    # NOTE: it's possible to make this faster by doing some upfront computation
    for target_file_path in all_file_paths:
        if does_relative_path_match_target_path_suffix(
            target_file_path, possible_relative_file_path
        ):
            return target_file_path
    return None
