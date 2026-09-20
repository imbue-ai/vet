"""
Regression tests: a response that does not parse as issue JSON must never collapse to "no issues".

Background: agentic passes (`--agentic --agent-harness claude`) were observed returning a prose
verdict with concrete findings. The prose failed schema parsing, the failure was logged and
skipped, and the run collated to `{"issues": []}` -- a false clean pass. These tests pin the
fixed behaviour: retry once with a JSON-only instruction, then fail hard with the raw response.
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from vet.cli.main import main
from vet.imbue_core.agents.llm_apis.data_types import CostedLanguageModelResponse
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelGenerationParams
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelResponseUsage
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelResponseWithLogits
from vet.imbue_core.agents.llm_apis.data_types import ResponseStopReason
from vet.imbue_core.agents.llm_apis.mock_api import LanguageModelMock
from vet.imbue_core.async_monkey_patches_test import expect_exact_logged_errors
from vet.imbue_core.data_types import IssueCode
from vet.imbue_core.frozen_utils import FrozenDict
from vet.imbue_tools.get_conversation_history.input_data_types import IdentifierInputs
from vet.imbue_tools.repo_utils.project_context import BaseProjectContext
from vet.imbue_tools.types.vet_config import VetConfig
from vet.issue_identifiers.agentic_issue_collation import collate_issues_with_agent
from vet.issue_identifiers.common import GeneratedIssueSchema
from vet.issue_identifiers.common import IssueResponseParsingError
from vet.issue_identifiers.common import generate_issues_from_agent
from vet.issue_identifiers.common import generate_issues_from_response_texts
from vet.issue_identifiers.common import get_agent_options
from vet.issue_identifiers.harnesses.agentic import AgenticHarness
from vet.issue_identifiers.harnesses.single_prompt import SinglePromptHarness
from vet.issue_identifiers.identification_guides import ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE
from vet.issue_identifiers.utils import ReturnCapturingGenerator

# Verbatim shape of the prose verdict observed in the field: real findings, no JSON anywhere.
PROSE_VERDICT = """All three fix-first items and the re-confirmation checklist check out correctly in the diff.
The one issue I'm flagging is a code-quality regression in the async conversion (missing `.catch()`
on the constructor's fire-and-forget invite issuance), not a break in any of the specific items
you asked me to verify -- those are all sound."""

SCHEMA_PARSE_ERROR = "Response does not match the expected schema"

VALID_ISSUE_RESPONSE = json.dumps(
    {
        "issues": [
            {
                "issue_code": "logic_error",
                "description": "Missing .catch() on fire-and-forget invite issuance",
                "location": "auth.ts",
                "severity": 3,
                "confidence": 0.8,
            }
        ]
    }
)

_OPTIONS = get_agent_options(cwd=None, model_name=None, agent_harness_type=VetConfig().agent_harness_type)


def _agent_side_effect(*responses: str) -> mock.Mock:
    """A stand-in for generate_response_from_agent that returns the given texts in order."""
    return mock.Mock(side_effect=[(text, []) for text in responses])


def test_generate_issues_from_response_texts_raises_instead_of_skipping() -> None:
    with expect_exact_logged_errors([SCHEMA_PARSE_ERROR]):
        with pytest.raises(IssueResponseParsingError) as excinfo:
            list(generate_issues_from_response_texts(response_texts=(PROSE_VERDICT,), phase="collation"))
    assert excinfo.value.raw_responses == (PROSE_VERDICT,)
    assert PROSE_VERDICT in str(excinfo.value)


def test_prose_verdict_is_retried_once_with_json_only_instruction() -> None:
    agent = _agent_side_effect(PROSE_VERDICT, VALID_ISSUE_RESPONSE)
    with mock.patch("vet.issue_identifiers.common.generate_response_from_agent", agent):
        with expect_exact_logged_errors([SCHEMA_PARSE_ERROR]):
            issues, _messages = generate_issues_from_agent("original prompt", _OPTIONS, phase="collation")

    assert [issue.description for issue in issues] == ["Missing .catch() on fire-and-forget invite issuance"]
    assert agent.call_count == 2
    retry_prompt = agent.call_args_list[1].args[0]
    assert "Respond with JSON only" in retry_prompt
    assert "Do not redo the analysis" in retry_prompt
    assert PROSE_VERDICT in retry_prompt
    assert '"issues"' in retry_prompt  # schema is restated


def test_prose_verdict_twice_is_a_hard_error_with_raw_response_attached() -> None:
    agent = _agent_side_effect(PROSE_VERDICT, PROSE_VERDICT + "\n(still prose)")
    with mock.patch("vet.issue_identifiers.common.generate_response_from_agent", agent):
        with expect_exact_logged_errors([SCHEMA_PARSE_ERROR, SCHEMA_PARSE_ERROR]):
            with pytest.raises(IssueResponseParsingError) as excinfo:
                generate_issues_from_agent("original prompt", _OPTIONS, phase="collation")

    assert agent.call_count == 2, "exactly one retry, never more"
    error = excinfo.value
    assert error.phase == "collation"
    assert len(error.raw_responses) == 2
    assert "(still prose)" in error.raw_responses[1]
    rendered = str(error)
    assert "after 2 attempts" in rendered
    assert "raw response (attempt 1)" in rendered and PROSE_VERDICT in rendered
    assert "(still prose)" in rendered


def _project_context(tmp_path: Path) -> BaseProjectContext:
    return BaseProjectContext(
        file_contents_by_path=FrozenDict({"auth.ts": "const x = 1;"}),
        cached_prompt_prefix="[ROLE=SYSTEM]\ntest",
        repo_path=tmp_path,
    )


def test_collation_of_prose_verdict_never_yields_zero_issues(tmp_path: Path) -> None:
    """The exact failure mode from the field: identification found issues, collation answered in prose."""
    identified = GeneratedIssueSchema(
        issue_code="logic_error", description="found upstream", severity=3, confidence=0.9
    )

    def identified_issues() -> Any:
        yield identified
        from vet.imbue_core.data_types import IssueIdentificationDebugInfo

        return IssueIdentificationDebugInfo(llm_responses=())

    agent = _agent_side_effect(PROSE_VERDICT, PROSE_VERDICT)
    collated = collate_issues_with_agent(
        identified_issues(),
        IdentifierInputs(maybe_goal="a specific enough goal for this review", maybe_diff="+const x = 1;"),
        _project_context(tmp_path),
        VetConfig(),
        (IssueCode.LOGIC_ERROR,),
        dict(ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE),
    )
    yielded: list[GeneratedIssueSchema] = []
    with mock.patch("vet.issue_identifiers.common.generate_response_from_agent", agent):
        with expect_exact_logged_errors([SCHEMA_PARSE_ERROR, SCHEMA_PARSE_ERROR]):
            with pytest.raises(IssueResponseParsingError) as excinfo:
                for issue in collated:
                    yielded.append(issue)

    assert yielded == [], "no partial/empty result may leak out before the error"
    assert excinfo.value.phase == "collation"
    assert agent.call_count == 2


def test_parallel_agentic_parse_failure_is_not_swallowed_by_per_type_error_handling(tmp_path: Path) -> None:
    """One issue type answering in prose must abort the run even when the other types succeed."""
    guides = (
        ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE[IssueCode.LOGIC_ERROR],
        ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE[IssueCode.RUNTIME_ERROR_RISK],
    )
    identifier = AgenticHarness().make_issue_identifier(identification_guides=guides)
    config = VetConfig(enable_parallel_agentic_issue_identification=True, max_identify_workers=2)

    def fake_agent(prompt: str, options: Any) -> tuple[str, list[Any]]:
        if "Respond with JSON only" in prompt or "runtime_error_risk" in prompt:
            return PROSE_VERDICT, []
        return json.dumps({"issues": []}), []

    inputs = identifier.to_required_inputs(
        IdentifierInputs(maybe_goal="a specific enough goal for this review", maybe_diff="+const x = 1;")
    )
    with mock.patch("vet.issue_identifiers.common.generate_response_from_agent", side_effect=fake_agent):
        with expect_exact_logged_errors([SCHEMA_PARSE_ERROR, SCHEMA_PARSE_ERROR]):
            with pytest.raises(IssueResponseParsingError) as excinfo:
                list(identifier.identify_issues(inputs, _project_context(tmp_path), config))
    assert "runtime_error_risk" in excinfo.value.phase


class _SequencedLanguageModelMock(LanguageModelMock):
    """Mock language model that answers with a fixed sequence of texts, recording every prompt."""

    responses: list[str] = []
    prompts: list[str] = []

    def complete_with_usage_sync(
        self,
        prompt: str,
        params: LanguageModelGenerationParams,
        is_caching_enabled: bool = True,
    ) -> CostedLanguageModelResponse:
        self.prompts.append(prompt)
        text = self.responses[len(self.prompts) - 1]
        response = LanguageModelResponseWithLogits(
            text=text,
            token_count=len(text.split()),
            stop_reason=ResponseStopReason.END_TURN,
            network_failure_count=0,
            token_probabilities=self._get_token_probabilities(text),
        )
        usage = LanguageModelResponseUsage(
            prompt_tokens_used=100, completion_tokens_used=50, dollars_used=0.001, caching_info=None
        )
        return CostedLanguageModelResponse(usage=usage, responses=(response,))


def test_single_prompt_harness_retries_prose_then_records_both_attempts() -> None:
    identifier = SinglePromptHarness().make_issue_identifier(
        identification_guides=(ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE[IssueCode.LOGIC_ERROR],)
    )
    language_model = _SequencedLanguageModelMock(responses=[PROSE_VERDICT, VALID_ISSUE_RESPONSE], prompts=[])
    project_context = BaseProjectContext(
        file_contents_by_path=FrozenDict({"auth.ts": "const x = 1;"}), cached_prompt_prefix="[ROLE=SYSTEM]\ntest"
    )
    inputs = identifier.to_required_inputs(
        IdentifierInputs(maybe_goal="a specific enough goal for this review", maybe_diff="+const x = 1;")
    )
    with mock.patch(
        "vet.issue_identifiers.harnesses.single_prompt.build_language_model_from_config",
        return_value=language_model,
    ):
        with expect_exact_logged_errors([SCHEMA_PARSE_ERROR]):
            generator = ReturnCapturingGenerator(identifier.identify_issues(inputs, project_context, VetConfig()))
            issues = list(generator)

    assert [issue.issue_code for issue in issues] == ["logic_error"]
    assert len(language_model.prompts) == 2
    assert "Respond with JSON only" in language_model.prompts[1]
    raw_responses = [llm_response.raw_response for llm_response in generator.return_value.llm_responses]
    assert raw_responses == [(PROSE_VERDICT,), (VALID_ISSUE_RESPONSE,)]


def test_cli_exits_nonzero_and_prints_raw_response_on_unparseable_verdict(tmp_path: Path, capsys: Any) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init"],
        cwd=repo,
        check=True,
    )
    output_path = tmp_path / "vet-output.json"
    env = {
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "ANTHROPIC_API_KEY": "test-key",
    }
    error = IssueResponseParsingError(phase="collation", reason="Invalid JSON", raw_responses=(PROSE_VERDICT,))

    with mock.patch.dict(os.environ, env):
        # configure_logging would tear down the logging handlers installed by test fixtures.
        with mock.patch("vet.cli.main.configure_logging"):
            with mock.patch("vet.api.find_issues", side_effect=error):
                exit_code = main(
                    [
                        "verify the SMTP client enforces TLS and never logs the password",
                        "--repo",
                        str(repo),
                        "--quiet",
                        "--output",
                        str(output_path),
                        "--output-format",
                        "json",
                    ]
                )

    assert exit_code == 1
    captured = capsys.readouterr()
    assert PROSE_VERDICT in captured.err
    assert "could not be parsed as issue JSON" in captured.err
    assert not output_path.exists(), 'a false `{"issues": []}` must never be written'
    assert "No issues found" not in captured.out
