from __future__ import annotations

from vet.formatters import (
    OUTPUT_FIELDS,
    _escape_github_annotation,
    format_issue_github,
    format_issue_text,
    issue_to_dict,
    issue_to_output,
)
from vet.imbue_core.data_types import (
    ConfidenceScore,
    IdentifiedVerifyIssue,
    IssueCode,
    IssueLocation,
    SeverityScore,
)


def _make_issue(
    *,
    code: IssueCode = IssueCode.INCORRECT_FUNCTION_IMPLEMENTATION,
    description: str = "Something is wrong",
    severity_raw: float = 3.0,
    confidence_raw: float = 0.85,
    filename: str | None = "src/foo.py",
    line_start: int = 42,
    line_end: int = 42,
) -> IdentifiedVerifyIssue:
    location = ()
    if filename is not None:
        location = (IssueLocation(line_start=line_start, line_end=line_end, filename=filename),)
    return IdentifiedVerifyIssue(
        code=code,
        description=description,
        severity_score=SeverityScore(raw=severity_raw, normalized=severity_raw / 5.0),
        confidence_score=ConfidenceScore(raw=confidence_raw, normalized=confidence_raw),
        location=location,
    )


# --- _escape_github_annotation ---


def test_escape_github_annotation_plain_text() -> None:
    assert _escape_github_annotation("hello world") == "hello world"


def test_escape_github_annotation_newlines() -> None:
    assert _escape_github_annotation("line1\nline2\nline3") == "line1%0Aline2%0Aline3"


def test_escape_github_annotation_carriage_return() -> None:
    assert _escape_github_annotation("a\r\nb") == "a%0D%0Ab"


def test_escape_github_annotation_percent_sign() -> None:
    assert _escape_github_annotation("100% done") == "100%25 done"


def test_escape_github_annotation_combined() -> None:
    assert _escape_github_annotation("100%\nok") == "100%25%0Aok"


# --- format_issue_github ---


def test_format_issue_github_basic() -> None:
    issue = _make_issue()
    result = format_issue_github(issue, OUTPUT_FIELDS)

    # severity 3 -> ::warning
    assert result.startswith("::warning ")
    assert "file=src/foo.py" in result
    assert "line=42" in result
    assert "title=[incorrect_function_implementation]" in result
    assert "Something is wrong" in result


def test_format_issue_github_high_severity_uses_error() -> None:
    issue = _make_issue(severity_raw=4.0)
    result = format_issue_github(issue, OUTPUT_FIELDS)
    assert result.startswith("::error ")


def test_format_issue_github_severity_5_uses_error() -> None:
    issue = _make_issue(severity_raw=5.0)
    result = format_issue_github(issue, OUTPUT_FIELDS)
    assert result.startswith("::error ")


def test_format_issue_github_low_severity_uses_warning() -> None:
    issue = _make_issue(severity_raw=1.0)
    result = format_issue_github(issue, OUTPUT_FIELDS)
    assert result.startswith("::warning ")


def test_format_issue_github_multiline_range() -> None:
    issue = _make_issue(line_start=10, line_end=20)
    result = format_issue_github(issue, OUTPUT_FIELDS)
    assert "line=10" in result
    assert "endLine=20" in result


def test_format_issue_github_single_line_no_endline() -> None:
    issue = _make_issue(line_start=10, line_end=10)
    result = format_issue_github(issue, OUTPUT_FIELDS)
    assert "line=10" in result
    assert "endLine" not in result


def test_format_issue_github_no_location() -> None:
    issue = _make_issue(filename=None)
    result = format_issue_github(issue, OUTPUT_FIELDS)

    # Should still produce a valid annotation, just without file/line params
    assert result.startswith("::warning ")
    assert "file=" not in result
    assert "line=" not in result
    assert "Something is wrong" in result


def test_format_issue_github_includes_confidence() -> None:
    issue = _make_issue(confidence_raw=0.92)
    result = format_issue_github(issue, OUTPUT_FIELDS)
    assert "Confidence: 0.92" in result


def test_format_issue_github_includes_severity_in_title() -> None:
    issue = _make_issue(severity_raw=3.0)
    result = format_issue_github(issue, OUTPUT_FIELDS)
    assert "(severity 3/5)" in result


def test_format_issue_github_respects_output_fields() -> None:
    issue = _make_issue()
    # Only include description, no issue_code, confidence, severity, or location fields
    result = format_issue_github(issue, ["description"])
    assert "Something is wrong" in result
    assert "title=" not in result
    assert "file=" not in result
    assert "Confidence" not in result


def test_format_issue_github_escapes_newlines_in_description() -> None:
    issue = _make_issue(description="Line one\nLine two")
    result = format_issue_github(issue, OUTPUT_FIELDS)
    # The message should have escaped newlines
    assert "Line one%0ALine two" in result
    # Should NOT contain a raw newline in the annotation command
    assert "\n" not in result


def test_format_issue_github_no_confidence_score() -> None:
    issue = _make_issue()
    issue = issue.model_copy(update={"confidence_score": None})
    result = format_issue_github(issue, OUTPUT_FIELDS)
    assert "Confidence" not in result


def test_format_issue_github_no_severity_score() -> None:
    issue = _make_issue()
    issue = issue.model_copy(update={"severity_score": None})
    result = format_issue_github(issue, OUTPUT_FIELDS)
    # Should default to ::warning when no severity
    assert result.startswith("::warning ")
    assert "severity" not in result.split("::")[1].split("::")[0]  # Not in title


# --- issue_to_output ---


def test_issue_to_output_extracts_fields() -> None:
    issue = _make_issue(line_start=10, line_end=20)
    output = issue_to_output(issue)

    assert output.file_path == "src/foo.py"
    assert output.line_number == 10
    assert output.line_number_end == 20
    assert output.issue_code == "incorrect_function_implementation"
    assert output.confidence == 0.85
    assert output.severity == 3.0
    assert output.description == "Something is wrong"


def test_issue_to_output_no_location() -> None:
    issue = _make_issue(filename=None)
    output = issue_to_output(issue)

    assert output.file_path is None
    assert output.line_number is None
    assert output.line_number_end is None


def test_issue_to_output_same_start_end_line() -> None:
    issue = _make_issue(line_start=42, line_end=42)
    output = issue_to_output(issue)
    assert output.line_number_end is None
