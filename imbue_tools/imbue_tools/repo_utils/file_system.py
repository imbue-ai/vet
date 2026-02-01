from typing import Generator
from typing import Mapping

from imbue_core.frozen_utils import FrozenDict
from imbue_core.frozen_utils import deep_freeze_mapping
from imbue_core.pydantic_serialization import SerializableModel


class SymlinkContents(SerializableModel):
    """A special type to represent a symbolic link in a file system."""

    target_path: str

    # Need to make SymlinkContents non-Iterable, or else deep_freeze_mapping will convert this to a tuple in InMemoryFileSystem.build.
    __iter__ = None  # type: ignore


DecodedTextFileContents = str
FileContents = bytes | SymlinkContents


class InMemoryFileSystem(SerializableModel):
    """
    A simple representation of in-memory file system. Can contain both text and binary files.
    """

    # Mapping from file path to contents
    files: FrozenDict[str, FileContents]
    # Only text files, decoded as UTF-8. Excludes symlinks and binary files.
    text_files: FrozenDict[str, DecodedTextFileContents]

    @classmethod
    def build(cls, files: Mapping[str, FileContents]) -> "InMemoryFileSystem":
        sorted_files = {k: v for k, v in sorted(files.items())}
        sorted_decoded_files: dict[str, DecodedTextFileContents | None] = {
            k: _try_decode_file_contents(c) for k, c in sorted_files.items()
        }
        sorted_text_files: dict[str, DecodedTextFileContents] = {
            k: c for k, c in sorted_decoded_files.items() if c is not None
        }
        return cls(
            files=deep_freeze_mapping(sorted_files),
            text_files=deep_freeze_mapping(sorted_text_files),
        )

    def get(self, file_path: str, default: FileContents | None = None) -> FileContents | None:
        if file_path in self.files:
            return self.files[file_path]
        return default

    def get_text(
        self, file_path: str, default: DecodedTextFileContents | None = None
    ) -> DecodedTextFileContents | None:
        """Get a the contents of a text file as a string. Returns `default` if the file does not exist, is a symlink, or is a binary file."""
        if file_path in self.text_files:
            return self.text_files[file_path]
        return default

    def __iter__(self) -> Generator[tuple[str, FileContents], None, None]:
        return (file for file in self.files.items())


def _try_decode_file_contents(contents: FileContents) -> DecodedTextFileContents | None:
    if isinstance(contents, SymlinkContents):
        return None
    else:
        assert isinstance(contents, bytes)
        try:
            return contents.decode("utf-8")
        except UnicodeDecodeError:
            return None
