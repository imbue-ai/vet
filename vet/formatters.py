from __future__ import annotations

from pydantic import BaseModel

from vet.imbue_core.data_types import IdentifiedVerifyIssue

OUTPUT_FORMATS = ["text", "json", "github"]

OUTPUT_FIELDS = [
    "issue_code",
    "confidence",
    "file_path",
    "line_number",
    "description",
    "severity",
]


class IssueOutput(BaseModel):
    """Pydantic model defining the CLI output schema for an identified issue."""

    issue_code: str
    confidence: float | None
    file_path: str | None
    line_number: int | None
    line_number_end: int | None = None
    description: str
    severity: float | None


def issue_to_output(issue: IdentifiedVerifyIssue) -> IssueOutput:
    line_number_end = None
    if issue.location and issue.location[0].line_end != issue.location[0].line_start:
        line_number_end = issue.location[0].line_end

    return IssueOutput(
        issue_code=str(issue.code),
        confidence=(issue.confidence_score.normalized if issue.confidence_score else None),
        file_path=issue.location[0].filename if issue.location else None,
        line_number=issue.location[0].line_start if issue.location else None,
        line_number_end=line_number_end,
        description=issue.description,
        severity=issue.severity_score.raw if issue.severity_score else None,
    )


def validate_output_fields(fields: list[str]) -> list[str]:
    invalid_fields = [f for f in fields if f not in OUTPUT_FIELDS]
    if invalid_fields:
        raise ValueError(f"Invalid output field(s): {', '.join(invalid_fields)}")
    return fields


def format_location(issue: IdentifiedVerifyIssue) -> str:
    if not issue.location:
        return ""
    loc = issue.location[0]
    location_str = f"{loc.filename}:{loc.line_start}"
    if loc.line_end != loc.line_start:
        location_str += f"-{loc.line_end}"
    return location_str


def format_issue_text(issue: IdentifiedVerifyIssue, fields: list[str]) -> str:
    lines = []

    location_str = format_location(issue)

    header_parts = []
    if "issue_code" in fields:
        header_parts.append(f"[{issue.code}]")
    if "file_path" in fields or "line_number" in fields:
        if location_str:
            header_parts.append(location_str)
    if header_parts:
        lines.append(" ".join(header_parts))

    if "description" in fields:
        lines.append(f"  Description: {issue.description}")
    if "confidence" in fields and issue.confidence_score:
        lines.append(f"  Confidence: {issue.confidence_score.normalized:.2f}")
    if "severity" in fields and issue.severity_score:
        lines.append(f"  Severity: {issue.severity_score.raw}/5")

    return "\n".join(lines)


def issue_to_dict(issue: IdentifiedVerifyIssue, fields: list[str]) -> dict:
    output = issue_to_output(issue)
    include_fields = set(fields)
    if "line_number" in fields and output.line_number_end is not None:
        include_fields.add("line_number_end")
    return output.model_dump(mode="json", include=include_fields)


def _escape_github_annotation(text: str) -> str:
    """Escape text for use in GitHub Actions workflow commands.

    GitHub Actions workflow commands use newlines as delimiters, so any newlines
    in the message must be percent-encoded. The `%` and `\r` characters must
    also be encoded to avoid ambiguity.
    """
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def format_issue_github(issue: IdentifiedVerifyIssue, fields: list[str]) -> str:
    """Format an issue as a GitHub Actions workflow command (::warning or ::error).

    These commands are parsed by GitHub Actions and rendered as annotations
    inline on the PR diff in the "Files changed" tab.
    """
    # Use ::error for severity >= 4, ::warning for lower
    severity_raw = issue.severity_score.raw if issue.severity_score else 0
    command = "error" if severity_raw >= 4 else "warning"

    # Build annotation parameters
    params: list[str] = []
    if issue.location and issue.location[0].filename and ("file_path" in fields or "line_number" in fields):
        loc = issue.location[0]
        params.append(f"file={loc.filename}")
        if "line_number" in fields:
            params.append(f"line={loc.line_start}")
            if loc.line_end != loc.line_start:
                params.append(f"endLine={loc.line_end}")

    # Build title
    title_parts: list[str] = []
    if "issue_code" in fields:
        title_parts.append(f"[{issue.code}]")
    if "severity" in fields and issue.severity_score:
        title_parts.append(f"(severity {issue.severity_score.raw:.0f}/5)")
    if title_parts:
        params.append(f"title={' '.join(title_parts)}")

    # Build message body
    message_parts: list[str] = []
    if "description" in fields:
        message_parts.append(issue.description)
    if "confidence" in fields and issue.confidence_score:
        message_parts.append(f"Confidence: {issue.confidence_score.normalized:.2f}")

    params_str = ",".join(params)
    message = " | ".join(message_parts)

    return f"::{command} {params_str}::{_escape_github_annotation(message)}"
