"""
Regression test: filtration must log when it silently drops raised issues, not just report a clean result.

Background: vet's default confidence threshold (0.8) discarded 16 of 16 raised findings on a real PR
(2026-09-20, wVet2b re-vet of PR #74) -- exit 0, `{"issues": []}`, nothing printed anywhere. Agentic
Claude seats on this codebase commonly score 0.4-0.8, so the default silently empties almost every run.
This pins the fix: a dropped issue is always logged at WARNING (the log-file sink in configure_logging
is unconditional regardless of -v), so the run is auditable after the fact even when nothing appears
on stderr at default verbosity.
"""

from contextlib import contextmanager
from typing import Any
from typing import Generator
from typing import Iterator

from loguru import logger

from vet.imbue_core.data_types import IssueIdentificationDebugInfo
from vet.imbue_core.frozen_utils import FrozenDict
from vet.imbue_tools.get_conversation_history.input_data_types import IdentifierInputs
from vet.imbue_tools.repo_utils.project_context import BaseProjectContext
from vet.imbue_tools.types.vet_config import VetConfig
from vet.issue_identifiers.common import GeneratedIssueSchema
from vet.issue_identifiers.identification_guides import ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE
from vet.issue_identifiers.issue_evaluation import filter_issues
from vet.issue_identifiers.utils import ReturnCapturingGenerator

_PROJECT_CONTEXT = BaseProjectContext(file_contents_by_path=FrozenDict(), cached_prompt_prefix="test")
_INPUTS = IdentifierInputs(maybe_goal="test", maybe_diff="test")
_GUIDES = dict(ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE)


@contextmanager
def capture_warnings() -> Iterator[list[str]]:
    """Capture loguru WARNING-level messages emitted during the block, independent of -v."""
    captured: list[str] = []

    def sink(message: Any) -> None:
        record = message.record
        if record["level"].name == "WARNING":
            captured.append(record["message"])

    handler_id = logger.add(sink, format="{message}", level="DEBUG")
    try:
        yield captured
    finally:
        logger.remove(handler_id)


def _issue(confidence: float) -> GeneratedIssueSchema:
    return GeneratedIssueSchema(
        issue_code="logic_error", description="a real finding", severity=3, confidence=confidence
    )


def _run_filter(
    issues: list[GeneratedIssueSchema], config: VetConfig
) -> tuple[list[GeneratedIssueSchema], IssueIdentificationDebugInfo]:
    def source() -> Generator[GeneratedIssueSchema, None, IssueIdentificationDebugInfo]:
        yield from issues
        return IssueIdentificationDebugInfo(llm_responses=())

    generator = ReturnCapturingGenerator(
        filter_issues(
            source(),
            _INPUTS,
            _PROJECT_CONTEXT,
            config,
            is_code_based_issue_generator=True,
            guides_by_issue_code=_GUIDES,
        )
    )
    filtered = list(generator)
    return filtered, generator.return_value


def test_all_issues_below_threshold_logs_the_drop() -> None:
    """The exact wVet2b shape: every finding scores below the 0.8 default, none survive."""
    config = VetConfig(filter_issues_below_confidence=0.8, filter_issues_through_llm_evaluator=False)
    issues = [_issue(c) for c in (0.75, 0.70, 0.60, 0.45)]

    with capture_warnings() as captured:
        results, _debug_info = _run_filter(issues, config)

    assert all(not r.passes_filtration for r in results), "no issue should have survived the 0.8 threshold"
    assert len(captured) == 1
    message = captured[0]
    assert "dropped 4 of 4 raised issue(s)" in message
    assert "4 below confidence threshold 0.8" in message
    assert "--confidence-threshold 0.0" in message


def test_no_drop_logs_nothing() -> None:
    """A clean pass with everything above threshold must not spuriously warn."""
    config = VetConfig(filter_issues_below_confidence=0.5, filter_issues_through_llm_evaluator=False)
    issues = [_issue(0.9), _issue(0.6)]

    with capture_warnings() as captured:
        results, _debug_info = _run_filter(issues, config)

    assert all(r.passes_filtration for r in results)
    assert captured == []


def test_low_threshold_surfaces_the_previously_hidden_findings() -> None:
    """The recommended fleet workaround (--confidence-threshold 0.0) actually surfaces everything."""
    config = VetConfig(filter_issues_below_confidence=0.0, filter_issues_through_llm_evaluator=False)
    issues = [_issue(c) for c in (0.75, 0.70, 0.60, 0.45)]

    results, _debug_info = _run_filter(issues, config)

    assert all(r.passes_filtration for r in results)
    assert len(results) == 4


def test_partial_drop_reports_both_counts() -> None:
    """A mixed batch must report drop count separately from total raised, not just pass/fail."""
    config = VetConfig(filter_issues_below_confidence=0.8, filter_issues_through_llm_evaluator=False)
    issues = [_issue(0.9), _issue(0.75), _issue(0.4)]

    with capture_warnings() as captured:
        results, _debug_info = _run_filter(issues, config)

    assert sum(1 for r in results if r.passes_filtration) == 1
    assert len(captured) == 1
    assert "dropped 2 of 3 raised issue(s)" in captured[0]
    assert "2 below confidence threshold 0.8" in captured[0]
