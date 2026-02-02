from abc import ABC
from abc import abstractmethod
from typing import Annotated

from pydantic import Tag

from vet.imbue_core.pydantic_serialization import SerializableModel
from vet.imbue_core.pydantic_serialization import build_discriminator


class FileContext(ABC, SerializableModel):
    object_type: str
    path: str

    @abstractmethod
    def format_for_agent(self) -> str:
        pass


class FullFileContext(FileContext):
    object_type: str = "FullFileContext"
    path: str
    contents: str = "RAW FILE CONTENTS"

    def format_for_agent(self) -> str:
        return f"<FILE>\n<PATH>\n{self.path}\n</PATH>\n<CONTENTS>\n{self.contents}\n</CONTENTS>\n</FILE>\n\n"


class FilenameContext(FileContext):
    object_type: str = "FilenameContext"
    path: str

    def format_for_agent(self) -> str:
        return f"<FILE>\n<PATH>\n{self.path}\n</PATH>\n</FILE>\n\n"


class StubFileContext(FileContext):
    object_type: str = "StubFileContext"
    path: str
    stub: str

    def format_for_agent(self) -> str:
        return f"<FILE>\n<PATH>\n{self.path}\n</PATH>\n<STUBIFIED_CONTENTS>\n{self.stub}\n</STUBIFIED_CONTENTS>\n</FILE>\n\n"


FileContextUnion = Annotated[
    Annotated[FullFileContext, Tag("FullFileContext")]
    | Annotated[FilenameContext, Tag("FilenameContext")]
    | Annotated[StubFileContext, Tag("StubFileContext")],
    build_discriminator(),
]
