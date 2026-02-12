"""
Tests for the SinglePromptHarness.
"""

import json
from unittest import mock

import pytest

from vet.imbue_core.agents.llm_apis.data_types import CostedLanguageModelResponse
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelGenerationParams
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelResponseUsage
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelResponseWithLogits
from vet.imbue_core.agents.llm_apis.data_types import ResponseStopReason
from vet.imbue_core.agents.llm_apis.mock_api import LanguageModelMock
from vet.imbue_core.data_types import IssueCode
from vet.imbue_core.frozen_utils import FrozenDict
from vet.imbue_tools.get_conversation_history.input_data_types import CommitInputs
from vet.imbue_tools.get_conversation_history.input_data_types import IdentifierInputs
from vet.imbue_tools.get_conversation_history.input_data_types import IdentifierInputsMissingError
from vet.imbue_tools.repo_utils.project_context import BaseProjectContext
from vet.imbue_tools.types.vet_config import VetConfig
from vet.issue_identifiers.base import IssueIdentifier
from vet.issue_identifiers.harnesses.single_prompt import SinglePromptHarness
from vet.issue_identifiers.identification_guides import ISSUE_CODES_FOR_CORRECTNESS_CHECK
from vet.issue_identifiers.identification_guides import ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE
from vet.issue_identifiers.utils import ReturnCapturingGenerator


class SinglePromptHarnessMock(LanguageModelMock):
    """Mock language model for testing SinglePromptHarness."""

    response_text: str = ""

    def complete_with_usage_sync(
        self,
        prompt: str,
        params: LanguageModelGenerationParams,
        is_caching_enabled: bool = True,
    ) -> CostedLanguageModelResponse:
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
