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


def _build_issue_header(
    issue: IdentifiedVerifyIssue,
    fields: list[str],
    *,
    bold_label: bool = False,
    severity_format: str = "g",
) -> str:
    label = "**Vet Issue**" if bold_label else "Vet Issue"
    parts: list[str] = [f"\U0001f534 {label}"]
    if "issue_code" in fields:
        parts.append(f"`{issue.code}`")
    meta: list[str] = []
    if "severity" in fields and issue.severity_score:
        meta.append(f"*severity: {issue.severity_score.raw:{severity_format}}/5*")
    if "confidence" in fields and issue.confidence_score:
        meta.append(f"*confidence: {issue.confidence_score.normalized:.2f}*")
    if meta:
        parts.append(", ".join(meta))
    return " ".join(parts)


def format_issue_text(issue: IdentifiedVerifyIssue, fields: list[str]) -> str:
    lines = []

    location_str = format_location(issue)
    lines.append(_build_issue_header(issue, fields))

    if "file_path" in fields or "line_number" in fields:
        if location_str:
            lines.append(f"  {location_str}")
    if "description" in fields:
        lines.append(f"  {issue.description}")

    return "\n".join(lines)


def issue_to_dict(issue: IdentifiedVerifyIssue, fields: list[str]) -> dict:
    output = issue_to_output(issue)
    include_fields = set(fields)
    if "line_number" in fields and output.line_number_end is not None:
        include_fields.add("line_number_end")
    return output.model_dump(mode="json", include=include_fields)


def _format_review_comment_body(issue: IdentifiedVerifyIssue, fields: list[str]) -> str:
    parts: list[str] = [
        _build_issue_header(issue, fields, bold_label=True, severity_format=".0f"),
    ]
    if "description" in fields:
        parts.append(issue.description)
    return "\n\n".join(parts)


def format_github_review(
    issues: tuple[IdentifiedVerifyIssue, ...],
    fields: list[str],
) -> dict:
    inline = [i for i in issues if i.location and i.location[0].filename]
    body_only = [i for i in issues if not i.location or not i.location[0].filename]

    count = len(issues)
    noun = "issue" if count == 1 else "issues"
    body = f"**Vet found {count} {noun}.**"
    if body_only:
        sections = [_format_review_comment_body(i, fields) for i in body_only]
        body += "\n\n---\n\n" + "\n\n".join(sections)

    comments = []
    for issue in inline:
        loc = issue.location[0]
        comment: dict = {
            "path": loc.filename,
            "line": loc.line_start,
            "side": "RIGHT",
            "body": _format_review_comment_body(issue, fields),
        }
        comments.append(comment)

    return {"body": body, "event": "COMMENT", "comments": comments}
