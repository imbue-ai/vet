"""
Tests for the SinglePromptHarness.
"""

import json
from unittest import mock

import pytest
from pydantic import Field
from syrupy.assertion import SnapshotAssertion

from vet.imbue_core.agents.llm_apis.data_types import CostedLanguageModelResponse
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelGenerationParams
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelResponseUsage
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelResponseWithLogits
from vet.imbue_core.agents.llm_apis.data_types import ResponseStopReason
from vet.imbue_core.agents.llm_apis.mock_api import LanguageModelMock
from vet.imbue_core.data_types import IssueCode
from vet.imbue_core.data_types import IssueIdentifierType
from vet.imbue_core.frozen_utils import FrozenDict
from vet.imbue_tools.get_conversation_history.input_data_types import CommitInputs
from vet.imbue_tools.get_conversation_history.input_data_types import IdentifierInputs
from vet.imbue_tools.get_conversation_history.input_data_types import (
    IdentifierInputsMissingError,
)
from vet.imbue_tools.repo_utils.project_context import BaseProjectContext
from vet.imbue_tools.types.vet_config import VetConfig
from vet.imbue_tools.types.vet_config import get_enabled_issue_codes
from vet.issue_identifiers.base import IssueIdentifier
from vet.issue_identifiers.harnesses.single_prompt import SinglePromptHarness
from vet.issue_identifiers.custom_guides import CustomGuideOverride
from vet.issue_identifiers.identification_guides import (
    ISSUE_CODES_FOR_CORRECTNESS_CHECK,
)
from vet.issue_identifiers.identification_guides import (
    ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE,
)
from vet.issue_identifiers.identification_guides import IssueIdentificationGuide
from vet.issue_identifiers.identification_guides import build_merged_guides
from vet.issue_identifiers.registry import _build_identifiers
from vet.issue_identifiers.registry import get_enabled_identifier_names
from vet.issue_identifiers.utils import ReturnCapturingGenerator


class SinglePromptHarnessMock(LanguageModelMock):
    """Mock language model for testing SinglePromptHarness."""

    response_text: str = ""
    captured_prompts: list[str] = Field(default_factory=list)

    def complete_with_usage_sync(
        self,
        prompt: str,
        params: LanguageModelGenerationParams,
        is_caching_enabled: bool = True,
    ) -> CostedLanguageModelResponse:
        self.captured_prompts.append(prompt)
        self.stats.complete_calls += 1
        response = LanguageModelResponseWithLogits(
            text=self.response_text,
            token_count=len(self.response_text.split()),
            stop_reason=ResponseStopReason.END_TURN,
            network_failure_count=0,
            token_probabilities=self._get_token_probabilities(self.response_text),
        )
        usage = LanguageModelResponseUsage(
            prompt_tokens_used=100,
            completion_tokens_used=50,
            dollars_used=0.001,
            caching_info=None,
        )
        return CostedLanguageModelResponse(usage=usage, responses=(response,))


def make_identifier() -> IssueIdentifier:
    harness = SinglePromptHarness()
    identifier = harness.make_issue_identifier(
        identification_guides=tuple(
            ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE[code] for code in ISSUE_CODES_FOR_CORRECTNESS_CHECK
        )
    )
    return identifier


def test_to_required_inputs() -> None:
    identifier = make_identifier()

    # Should support inputs where only the commit message and diff are present
    commit_inputs = IdentifierInputs(maybe_goal="test", maybe_diff="test")
    cmi = identifier.to_required_inputs(commit_inputs)
    assert isinstance(cmi, CommitInputs)

    # Should support inputs where the commit message and diff are present
    combined_inputs = IdentifierInputs(
        maybe_goal="test",
        maybe_diff="test",
        maybe_files=("test.py",),
        maybe_conversation_history=(),
    )
    cmi = identifier.to_required_inputs(combined_inputs)
    assert isinstance(cmi, CommitInputs)

    # Should not support inputs where the commit message and diff are absent
    file_inputs = IdentifierInputs(maybe_files=("test.py",))
    with pytest.raises(IdentifierInputsMissingError):
        identifier.to_required_inputs(file_inputs)
    no_inputs = IdentifierInputs()
    with pytest.raises(IdentifierInputsMissingError):
        identifier.to_required_inputs(no_inputs)

    # Should not support inputs where only one of the commit message and diff are present
    commit_message_inputs = IdentifierInputs(maybe_goal="test", maybe_conversation_history=())
    with pytest.raises(IdentifierInputsMissingError):
        identifier.to_required_inputs(commit_message_inputs)
    diff_inputs = IdentifierInputs(maybe_diff="test")
    with pytest.raises(IdentifierInputsMissingError):
        identifier.to_required_inputs(diff_inputs)


def test_get_prompt_structure() -> None:
    identifier = make_identifier()
    project_context = BaseProjectContext(
        file_contents_by_path=FrozenDict({"test.py": "print('hello')"}),
        cached_prompt_prefix="[ROLE=SYSTEM]\nSystem context here",
    )
    commit_inputs = CommitInputs(
        maybe_goal="Add hello world function",
        maybe_diff="+def hello():\n+    print('hello')",
    )
    config = VetConfig()

    prompt = identifier._get_prompt(project_context, config, commit_inputs)

    # Check that prompt contains key elements
    assert "System context here" in prompt
    assert "Add hello world function" in prompt
    assert "+def hello():" in prompt
    assert "logic_error" in prompt
    assert "runtime_error_risk" in prompt
    assert "issues" in prompt
    assert "schema" in prompt.lower()  # Should contain schema from pydantic model


def test_identify_issues_integration() -> None:
    """Test the full identify_issues flow with mocked LLM."""
    identifier = make_identifier()

    # Create mock language model with specific response
    response_text = json.dumps(
        {
            "issues": [
                {
                    "issue_code": "logic_error",
                    "description": "Test logic error",
                    "severity": 4,
                    "confidence": 0.9,
                }
            ]
        }
    )

    mock_language_model = SinglePromptHarnessMock(response_text=response_text)
    with mock.patch(
        "vet.issue_identifiers.harnesses.single_prompt.build_language_model_from_config",
        return_value=mock_language_model,
    ):
        project_context = BaseProjectContext(
            file_contents_by_path=FrozenDict({"test.py": "print('hello')"}),
            cached_prompt_prefix="[ROLE=SYSTEM]\nSystem context",
        )
        commit_inputs = IdentifierInputs(maybe_goal="Add hello function", maybe_diff="+print('hello')")
        config = VetConfig()

        inputs = identifier.to_required_inputs(commit_inputs)
        raw_issues_generator = identifier.identify_issues(inputs, project_context, config)
        raw_issues = []
        raw_issues_generator_with_capture = ReturnCapturingGenerator(raw_issues_generator)
        for raw_issue in raw_issues_generator_with_capture:
            raw_issues.append(raw_issue)
        llm_responses = raw_issues_generator_with_capture.return_value.llm_responses

        assert len(raw_issues) == 1
        assert raw_issues[0].issue_code == IssueCode.LOGIC_ERROR
        assert raw_issues[0].description == "Test logic error"
        assert len(llm_responses) > 0  # Should have LLM responses


def _build_single_prompt_identifier(
    guides_by_code: dict[IssueCode, IssueIdentificationGuide] | None = None,
) -> IssueIdentifier:
    """Build the single prompt identifier via the production path (_build_identifiers)."""
    config = VetConfig()
    if guides_by_code is None:
        guides_by_code = config.guides_by_code
    identifiers = _build_identifiers(
        get_enabled_identifier_names(config),
        get_enabled_issue_codes(config),
        guides_by_code,
    )
    for name, identifier in identifiers:
        if IssueIdentifierType.CORRECTNESS_COMMIT_CLASSIFIER.value in name:
            return identifier
    raise ValueError("Single prompt identifier not found")


SNAPSHOT_PROJECT_CONTEXT = BaseProjectContext(
    file_contents_by_path=FrozenDict({"test.py": "print('hello')"}),
    cached_prompt_prefix="[ROLE=SYSTEM]\nSystem context here",
)
SNAPSHOT_COMMIT_INPUTS = CommitInputs(
    maybe_goal="Add hello world function",
    maybe_diff="+def hello():\n+    print('hello')",
)


def test_prompt_snapshot(snapshot: SnapshotAssertion) -> None:
    """Snapshot the exact prompt sent to the LLM to catch unintended prompt regressions."""
    identifier = _build_single_prompt_identifier()
    prompt = identifier._get_prompt(SNAPSHOT_PROJECT_CONTEXT, VetConfig(), SNAPSHOT_COMMIT_INPUTS)
    assert prompt == snapshot


def test_prompt_snapshot_with_custom_guides(snapshot: SnapshotAssertion) -> None:
    """Snapshot prompt with multiple custom guide override modes applied simultaneously.

    Covers all override modes across different issue codes:
    - logic_error: prefix only
    - runtime_error_risk: suffix only
    - incorrect_algorithm: replace (fully replaces the default guide)
    - error_handling_missing: prefix + suffix combined
    - async_correctness: prefix + replace (conflict: replace takes precedence)
    - type_safety_violation: left as default (no override)
    - correctness_syntax_issues: left as default (no override)
    """
    merged_guides = build_merged_guides(
        {
            IssueCode.LOGIC_ERROR: CustomGuideOverride(
                issue_code=IssueCode.LOGIC_ERROR,
                prefix="CUSTOM PREFIX: Always check edge cases for off-by-one errors.",
            ),
            IssueCode.RUNTIME_ERROR_RISK: CustomGuideOverride(
                issue_code=IssueCode.RUNTIME_ERROR_RISK,
                suffix="CUSTOM SUFFIX: Pay special attention to null pointer dereferences.",
            ),
            IssueCode.INCORRECT_ALGORITHM: CustomGuideOverride(
                issue_code=IssueCode.INCORRECT_ALGORITHM,
                replace="CUSTOM REPLACEMENT: This entirely replaces the default incorrect_algorithm guide.",
            ),
            IssueCode.ERROR_HANDLING_MISSING: CustomGuideOverride(
                issue_code=IssueCode.ERROR_HANDLING_MISSING,
                prefix="CUSTOM PREFIX: Check all I/O operations.",
                suffix="CUSTOM SUFFIX: Ensure timeouts are set for network calls.",
            ),
            IssueCode.ASYNC_CORRECTNESS: CustomGuideOverride(
                issue_code=IssueCode.ASYNC_CORRECTNESS,
                prefix="CUSTOM PREFIX (should be ignored due to replace taking precedence).",
                replace="CUSTOM REPLACE WINS: Replace takes precedence over prefix.",
            ),
        }
    )
    identifier = _build_single_prompt_identifier(guides_by_code=merged_guides)
    prompt = identifier._get_prompt(SNAPSHOT_PROJECT_CONTEXT, VetConfig(), SNAPSHOT_COMMIT_INPUTS)
    assert prompt == snapshot
