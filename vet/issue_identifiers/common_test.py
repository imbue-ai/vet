import json
from pathlib import Path
from typing import Iterable

from vet.imbue_core.async_monkey_patches_test import expect_exact_logged_errors
from vet.imbue_core.data_types import IdentifiedVerifyIssue
from vet.imbue_core.data_types import IssueCode
from vet.imbue_core.frozen_utils import FrozenDict
from vet.imbue_core.itertools import only
from vet.imbue_tools.llm_output_parsing.parse_model_json_response import ResponseParsingError
from vet.imbue_tools.llm_output_parsing.parse_model_json_response import parse_model_json_response
from vet.imbue_tools.repo_utils.project_context import BaseProjectContext
from vet.imbue_tools.repo_utils.project_context import ProjectContext
from vet.issue_identifiers.common import GeneratedResponseSchema
from vet.issue_identifiers.common import convert_generated_issue_to_identified_issue
from vet.issue_identifiers.common import format_issue_identification_guide_for_llm
from vet.issue_identifiers.identification_guides import ISSUE_CODES_FOR_CORRECTNESS_CHECK
from vet.issue_identifiers.identification_guides import IssueIdentificationGuide


def _parse_issues(
    valid_response: str,
    project_context: ProjectContext,
    enabled_issue_codes: Iterable[IssueCode],
) -> list[IdentifiedVerifyIssue]:
    issues = []
    try:
        issue_data = parse_model_json_response(valid_response, GeneratedResponseSchema)
    except ResponseParsingError:
        return []
    for parsed_issue in issue_data.issues:
        issue = convert_generated_issue_to_identified_issue(
            issue_data=parsed_issue,
            project_context=project_context,
            enabled_issue_codes=tuple(enabled_issue_codes),
        )
        if issue:
            issues.append(issue)
    return issues


def test_parse_issues_valid_json() -> None:
    project_context = BaseProjectContext(
        file_contents_by_path=FrozenDict({"test.py": "def test():\n    while True:\n        pass"}),
        cached_prompt_prefix="test",
    )

    valid_response = json.dumps(
        {
            "issues": [
                {
                    "issue_code": "logic_error",
                    "description": "Infinite loop detected",
                    "location": "test.py",
                    "code_part": "while True:\n        pass",
                    "severity": 5,
                    "confidence": 0.95,
                }
            ]
        }
    )

    issues = _parse_issues(valid_response, project_context, ISSUE_CODES_FOR_CORRECTNESS_CHECK)

    issue = only(issues)
    assert issue.code == IssueCode.LOGIC_ERROR
    assert issue.description == "Infinite loop detected"
    assert issue.confidence_score is not None
    assert issue.confidence_score.normalized == 0.95
    assert issue.severity_score is not None
    assert issue.severity_score.normalized == 1.0  # severity 5 maps to 1.0
    assert len(issue.location) == 1
    assert issue.location[0].filename == "test.py"


def test_parse_response_with_leading_and_trailing_text() -> None:
    project_context = BaseProjectContext(file_contents_by_path=FrozenDict(), cached_prompt_prefix="test")
    valid_response = json.dumps(
        {
            "issues": [
                {
                    "issue_code": "logic_error",
                    "description": "Infinite loop detected",
                    "location": "test.py",
                    "code_part": "while True:\n        pass",
                    "severity": 5,
                    "confidence": 0.95,
                }
            ]
        }
    )

    response_text = "Some leading text\n```json\n" + valid_response + "\n```\nSome trailing text"
    # Note: This logs a warning about "Unknown location" since test.py isn't in the project context
    issues = _parse_issues(response_text, project_context, ISSUE_CODES_FOR_CORRECTNESS_CHECK)
    issue = only(issues)
    assert issue.code == IssueCode.LOGIC_ERROR
    assert issue.description == "Infinite loop detected"
    assert issue.confidence_score is not None
    assert issue.confidence_score.normalized == 0.95
    assert issue.severity_score is not None
    assert issue.severity_score.normalized == 1.0  # severity 5 maps to 1.0


def test_parse_issues_empty_response() -> None:
    project_context = BaseProjectContext(file_contents_by_path=FrozenDict(), cached_prompt_prefix="test")

    empty_response = json.dumps({"issues": []})

    issues = _parse_issues(empty_response, project_context, ISSUE_CODES_FOR_CORRECTNESS_CHECK)
    assert len(issues) == 0


def test_parse_issues_invalid_json() -> None:
    project_context = BaseProjectContext(file_contents_by_path=FrozenDict(), cached_prompt_prefix="test")

    invalid_response = "not json"

    with expect_exact_logged_errors(["Response does not match the expected schema"]):
        issues = _parse_issues(invalid_response, project_context, ISSUE_CODES_FOR_CORRECTNESS_CHECK)
    assert len(issues) == 0


def test_parse_issues_with_markdown_formatting() -> None:
    project_context = BaseProjectContext(
        file_contents_by_path=FrozenDict({"test.py": "x = 1"}),
        cached_prompt_prefix="test",
    )

    markdown_response = (
        "```json\n"
        + json.dumps(
            {
                "issues": [
                    {
                        "issue_code": "runtime_error_risk",
                        "description": "Test issue",
                        "severity": 3,
                        "confidence": 0.8,
                    }
                ]
            }
        )
        + "\n```"
    )

    issues = _parse_issues(markdown_response, project_context, ISSUE_CODES_FOR_CORRECTNESS_CHECK)
    assert len(issues) == 1
    assert issues[0].code == IssueCode.RUNTIME_ERROR_RISK


def test_parse_issues_invalid_severity() -> None:
    project_context = BaseProjectContext(file_contents_by_path=FrozenDict(), cached_prompt_prefix="test")

    invalid_severity_response = json.dumps(
        {
            "issues": [
                {
                    "issue_code": "logic_error",
                    "description": "Test issue",
                    "severity": 10,  # Invalid - should be 1-5
                    "confidence": 0.8,
                }
            ]
        }
    )

    with expect_exact_logged_errors(["Response does not match the expected schema"]):
        issues = _parse_issues(
            invalid_severity_response,
            project_context,
            ISSUE_CODES_FOR_CORRECTNESS_CHECK,
        )
    assert len(issues) == 0  # Should be skipped due to invalid severity


def test_parse_issues_unknown_issue_code() -> None:
    project_context = BaseProjectContext(file_contents_by_path=FrozenDict(), cached_prompt_prefix="test")

    unknown_code_response = json.dumps(
        {
            "issues": [
                {
                    "issue_code": "unknown_issue",  # Not in our defined codes
                    "description": "Test issue",
                    "severity": 3,
                    "confidence": 0.8,
                }
            ]
        }
    )

    with expect_exact_logged_errors(["Got issue code"]):
        issues = _parse_issues(unknown_code_response, project_context, ISSUE_CODES_FOR_CORRECTNESS_CHECK)
    assert len(issues) == 0  # Should be skipped due to unknown code


def test_parse_issues_missing_required_fields() -> None:
    project_context = BaseProjectContext(file_contents_by_path=FrozenDict(), cached_prompt_prefix="[ROLE=SYSTEM]\ntest")

    # Missing required field 'confidence'
    missing_field_response = json.dumps(
        {
            "issues": [
                {
                    "issue_code": "logic_error",
                    "description": "Test issue",
                    "severity": 3,
                    # Missing 'confidence' field
                }
            ]
        }
    )

    with expect_exact_logged_errors(["Response does not match the expected schema"]):
        issues = _parse_issues(missing_field_response, project_context, ISSUE_CODES_FOR_CORRECTNESS_CHECK)
    assert len(issues) == 0  # Should be skipped due to missing field


def test_parse_issues_invalid_confidence() -> None:
    project_context = BaseProjectContext(file_contents_by_path=FrozenDict(), cached_prompt_prefix="[ROLE=SYSTEM]\ntest")

    invalid_confidence_response = json.dumps(
        {
            "issues": [
                {
                    "issue_code": "logic_error",
                    "description": "Test issue",
                    "severity": 3,
                    "confidence": 1.5,  # Invalid - should be 0.0-1.0
                }
            ]
        }
    )

    with expect_exact_logged_errors(["Response does not match the expected schema"]):
        issues = _parse_issues(
            invalid_confidence_response,
            project_context,
            ISSUE_CODES_FOR_CORRECTNESS_CHECK,
        )
    assert len(issues) == 0  # Should be skipped due to invalid confidence


def test_parse_issues_with_line_ranges() -> None:
    code_content = "def hello():\n    print('world')\n    return True"
    project_context = BaseProjectContext(
        file_contents_by_path=FrozenDict({"test.py": code_content}),
        cached_prompt_prefix="[ROLE=SYSTEM]\ntest",
    )

    response_with_location = json.dumps(
        {
            "issues": [
                {
                    "issue_code": "logic_error",
                    "description": "Test issue with location",
                    "location": "test.py",
                    "code_part": "print('world')",
                    "severity": 3,
                    "confidence": 0.8,
                }
            ]
        }
    )

    issues = _parse_issues(response_with_location, project_context, ISSUE_CODES_FOR_CORRECTNESS_CHECK)
    issue = only(issues)
    assert issue.location[0].filename == "test.py"
    assert len(issue.location) > 0  # Should have found line ranges


def test_parse_issues_malformed_response_structure() -> None:
    project_context = BaseProjectContext(file_contents_by_path=FrozenDict(), cached_prompt_prefix="[ROLE=SYSTEM]\ntest")

    # Test with non-dict response
    non_dict_response = json.dumps(["not", "a", "dict"])
    with expect_exact_logged_errors(["Response does not match the expected schema"]):
        issues = _parse_issues(non_dict_response, project_context, ISSUE_CODES_FOR_CORRECTNESS_CHECK)
    assert len(issues) == 0

    # Test with missing `issues` key
    missing_key_response = json.dumps({"other_key": ["some value", "another value"]})
    # note that this doesn't log an error; the model validation allows "issues" to be missing, and fills in an empty list
    issues = _parse_issues(missing_key_response, project_context, ISSUE_CODES_FOR_CORRECTNESS_CHECK)
    assert len(issues) == 0

    # Test with missing everything
    missing_everything_response = json.dumps({})
    # note that this doesn't log an error; the model validation allows "issues" to be missing, and fills in an empty list
    issues = _parse_issues(missing_everything_response, project_context, ISSUE_CODES_FOR_CORRECTNESS_CHECK)
    assert len(issues) == 0

    # Test with non-list `issues` value
    non_list_response = json.dumps({"issues": "not a list"})
    with expect_exact_logged_errors(["Response does not match the expected schema"]):
        issues = _parse_issues(non_list_response, project_context, ISSUE_CODES_FOR_CORRECTNESS_CHECK)
    assert len(issues) == 0


def test_format_issue_identification_guide_for_llm() -> None:
    complete_guide = IssueIdentificationGuide(
        issue_code=IssueCode.LOGIC_ERROR,
        guide="- Guideline 1\n- Guideline 2",
        examples=(
            "Example 1",
            "Example 2",
        ),
        exceptions=(
            "Exception 1",
            "Exception 2",
        ),
    )

    expected_formatted_complete_guide = """Guidelines:
    - Guideline 1
    - Guideline 2
Examples:
    - Example 1
    - Example 2
Exceptions:
    - Exception 1
    - Exception 2"""

    minimal_guide = IssueIdentificationGuide(issue_code=IssueCode.LOGIC_ERROR, guide="Only has a guide.")
    expected_formatted_minimal_guide = """Guidelines:
    Only has a guide."""

    formatted_complete_guide = format_issue_identification_guide_for_llm(complete_guide)
    assert formatted_complete_guide == expected_formatted_complete_guide

    formatted_minimal_guide = format_issue_identification_guide_for_llm(minimal_guide)
    assert formatted_minimal_guide == expected_formatted_minimal_guide


def test_strips_absolute_filenames() -> None:
    project_context = BaseProjectContext(
        file_contents_by_path=FrozenDict({"test.py": "def test():\n    while True:\n        pass"}),
        cached_prompt_prefix="test",
        repo_path=Path("/code"),
    )

    valid_response = json.dumps(
        {
            "issues": [
                {
                    "issue_code": "logic_error",
                    "description": "Infinite loop detected",
                    "location": "/code/test.py",
                    "code_part": "while True:\n        pass",
                    "severity": 5,
                    "confidence": 0.95,
                }
            ]
        }
    )

    issues = _parse_issues(valid_response, project_context, ISSUE_CODES_FOR_CORRECTNESS_CHECK)

    issue = only(issues)
    assert issue.description == "Infinite loop detected"
    assert len(issue.location) == 1
    assert issue.location[0].filename == "test.py"
