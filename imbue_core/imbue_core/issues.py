from enum import StrEnum
from typing import Annotated

from pydantic import Tag

from imbue_core.pydantic_serialization import SerializableModel
from imbue_core.pydantic_serialization import build_discriminator


class IssueSeverityLevel(StrEnum):
    CRITICAL = "CRITICAL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    NIT = "NIT"


class IssueKey(SerializableModel):
    # issues from different commands should not collide
    command: str
    # this should NOT contain line numbers, as we want it to be stable across changes as much as possible
    # NOTE: we do some initial formatting to avoid issues around message containing code
    identifier: str


class Issue(SerializableModel):
    key: IssueKey
    severity: IssueSeverityLevel

    def is_equal(self, other: "Issue") -> bool:
        return self.key == other.key

    def summary_line(self) -> str:
        return f"{self.severity}: {self.key}"


class CheckFailedIssue(Issue):
    object_type: str = "CheckFailedIssue"
    error_message: str

    raw: str | None = None


class IdentifiedIssue(Issue):
    object_type: str = "IdentifiedIssue"
    issue_location: str | None = None

    # The oneliner message of the problem.
    # PYTEST: AssertionError
    # MYPY: error: Function is missing a type annotation
    message: str

    # The full description of the issue (can be many lines)
    # Examples:
    # PYTEST: the longrepr, which is "def test_pearson_correlation_basic_lists():\n x = [1, 2, 3, 4, 5]\n y = [2, 4, 6, 8, 10]\n expected_correlation = 0.9819805060619657\n>    ..."  # noqa
    # MYPY: "def calculate_pearson_correlation(x, y):"
    description: str

    def summary_line(self) -> str:
        return f"{super().summary_line()} message={self.message!r}" + (
            f" ({self.issue_location})" if self.issue_location else ""
        )


IssueUnion = Annotated[
    (Annotated[CheckFailedIssue, Tag("CheckFailedIssue")] | Annotated[IdentifiedIssue, Tag("IdentifiedIssue")]),
    build_discriminator(),
]
