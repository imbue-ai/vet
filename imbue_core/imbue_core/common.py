import functools
import hashlib
import inspect
import os
import platform
import sys
import uuid
from pathlib import Path
from types import FrameType

import pathspec


def is_on_osx() -> bool:
    return platform.system().lower() == "darwin"


def is_running_within_a_pytest_tree() -> bool:
    """
    This is true if this, or any parent process, is running under pytest.

    This is different from `is_running_within_a_pytest_process` in that it is true if we are logically testing or not.

    This is usually what you want to check
    (eg, this will be true even if you are a separately launched integration server process)
    """
    return "PYTEST_CURRENT_TEST" in os.environ


def is_running_within_a_pytest_process() -> bool:
    """
    This is true if the current process is literally running pytest.

    This is different from `is_running_within_a_pytest_tree` in that it checks if the current process is pytest itself,
    which is most useful for knowing whether we are running a bunch of unit tests in this process or not.
    """
    return "pytest" in sys.modules


def is_live_debugging() -> bool:
    """
    Returns True if the current process is being debugged, for example by PyCharm or another IDE.
    """
    # this is unfortunately true when measuring coverage and in other cases, sigh
    # return sys.gettrace() is not None
    # but this is only true when debugging in pycharm, I think?
    return sys.breakpointhook.__module__ != "sys"


@functools.lru_cache(maxsize=1)
def get_filesystem_root() -> str:
    env_value = os.getenv("SCIENCE_FILESYSTEM_ROOT")
    if not env_value:
        if is_on_osx():
            return "/tmp/science"
        else:
            # When on the physical cluster (and possibly other core clusters), this path is mounted to a unique per-container file path.
            # Anything produced at runtime >10mb should likely go here, as well as anything you might want to dig up for later debugging.
            # The hosts clean up the paths from dead containers periodically, but large data processing jobs should still clean up after themselves.
            return "/mnt/private"
    return env_value


@functools.lru_cache(maxsize=1)
def get_temp_dir() -> str:
    temp_dir = os.path.join(get_filesystem_root(), "tmp")
    os.makedirs(temp_dir, exist_ok=True)
    return temp_dir


def hash_string(string: str) -> str:
    return hashlib.md5(string.encode("utf-8")).hexdigest()


def get_current_function_name() -> str:
    frame = inspect.currentframe()
    if frame is None:
        return "no_frame"
    prev_frame = frame.f_back
    if prev_frame is None or not isinstance(prev_frame, FrameType):
        return "no_previous_frame"
    return prev_frame.f_code.co_name


def filter_excluded_files(files: list[Path], directory: Path, exclude_file_name: str = ".gitignore") -> list[Path]:
    """Remove files from the list that are matched by a .gitignore or similarly-specified exclude file such as
    .gitignore or ratchet_excluded.txt.
    """

    # Underneath the root directory, find all the excluders.
    # They can occur in subfolders and if they do they apply only to that subfolder.
    excluders = {path for path in directory.rglob(exclude_file_name) if not path.is_symlink()}

    # Per excluder, make a pathspec.
    for excluder in excluders:
        with excluder.open("r") as exclude_file:
            exclude_spec = pathspec.GitIgnoreSpec.from_lines(exclude_file)

            # Now we have two cases - We keep the file if the excluder doesn't apply because it's in a different
            # folder, or if it applies but doesn't match
            prefix = os.path.dirname(excluder)
            files = [
                file
                for file in files
                if not (file.is_relative_to(prefix) and exclude_spec.match_file(file.relative_to(prefix)))
            ]

    return files


def generate_id() -> str:
    return uuid.uuid4().hex


def generate_id_from_existing_id(existing_id: str, seed: int) -> str:
    return hashlib.md5(f"{existing_id}-{seed}".encode()).hexdigest()


def truncate_string(s: str, max_length: int) -> str:
    if len(s) <= max_length:
        return s
    return s[: max_length - 3] + "..."


def parse_bool_environment_variable(var_name: str) -> bool:
    env_var = os.environ.get(var_name, "0").lower()

    assert env_var in (
        "0",
        "1",
        "true",
        "false",
    ), f"{var_name} environment variable must be '0', '1', 'true', or 'false'. Current value: '{env_var}'"

    return env_var in ("1", "true")
