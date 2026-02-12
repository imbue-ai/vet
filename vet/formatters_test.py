from __future__ import annotations

from syrupy.assertion import SnapshotAssertion

from vet.formatters import OUTPUT_FIELDS
from vet.formatters import format_github_review
from vet.imbue_core.data_types import ConfidenceScore
from vet.imbue_core.data_types import IdentifiedVerifyIssue
from vet.imbue_core.data_types import IssueCode
from vet.imbue_core.data_types import IssueLocation
from vet.imbue_core.data_types import SeverityScore


def _make_issue(
    *,
    description: str = "Buffer overflow",
    severity_raw: float = 2.5,
    confidence_raw: float = 0.75,
    filename: str | None = "src/foo.py",
    line_start: int = 40,
    line_end: int = 50,
) -> IdentifiedVerifyIssue:
    location = ()
    if filename is not None:
        location = (IssueLocation(line_start=line_start, line_end=line_end, filename=filename),)
    return IdentifiedVerifyIssue(
        issue_id="test-issue-id",
        code=IssueCode.INCORRECT_FUNCTION_IMPLEMENTATION,
        description=description,
        severity_score=SeverityScore(raw=severity_raw, normalized=severity_raw / 5.0),
        confidence_score=ConfidenceScore(raw=confidence_raw, normalized=confidence_raw),
        location=location,
    )


def test_format_github_review_no_issues(snapshot: SnapshotAssertion) -> None:
    assert format_github_review((), OUTPUT_FIELDS) == snapshot


def test_format_github_review_mixed_issues(snapshot: SnapshotAssertion) -> None:
    inline_issue = _make_issue(description="This function has a bug", filename="src/app.py", line_start=10)
    body_issue = _make_issue(description="General architecture concern", filename=None)
    assert format_github_review((inline_issue, body_issue), OUTPUT_FIELDS) == snapshot
