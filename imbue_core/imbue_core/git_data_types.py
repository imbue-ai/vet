from datetime import datetime
from typing import Annotated

from pydantic.functional_validators import PlainValidator

from imbue_core.pydantic_serialization import FrozenModel
from imbue_core.pydantic_serialization import SerializableModel


def _validate_git_timestamp(value: str) -> str:
    try:
        datetime.fromisoformat(value)
        return value
    except ValueError:
        raise ValueError(f"Invalid git timestamp: {value}")


class CommitTimestamp(SerializableModel):
    author_ts: Annotated[str, PlainValidator(_validate_git_timestamp)]
    committer_ts: Annotated[str, PlainValidator(_validate_git_timestamp)]


class CommitMetadata(FrozenModel):
    commit: str
    tree_hash: str
    message: str
    commit_time: CommitTimestamp

    @property
    def body(self) -> str:
        return self.message.split("\n", 1)[-1]

    @property
    def subject(self) -> str:
        return self.message.split("\n", 1)[0]
