import pytest
from loguru import logger

from vet.imbue_core.data_types import IssueCode
from vet.imbue_tools.types.vet_config import VetConfig
from vet.issue_identifiers import registry
from vet.issue_identifiers.custom_guides import CustomGuideOverride
from vet.issue_identifiers.harnesses.agentic import AgenticHarness
from vet.issue_identifiers.harnesses.conversation_single_prompt import ConversationSinglePromptHarness
from vet.issue_identifiers.harnesses.single_prompt import SinglePromptHarness
from vet.issue_identifiers.identification_guides import (
    ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE,
    merge_guide_with_custom,
)

DEFAULT_VET_CONFIG = VetConfig()

# 200 single-token words for testing overhead sensitivity.
_CUSTOM_SUFFIX_TOKENS = 200
_CUSTOM_SUFFIX = " ".join(["test"] * _CUSTOM_SUFFIX_TOKENS)
VET_MAX_PROMPT_TOKENS = 10_000


def test_prompt_lengths() -> None:
    """
    Test that calculated prompt overheads don't exceed the expected limit.

    This verifies that each harness's calculate_prompt_overhead() method
    returns reasonable token counts for prompts with all issue codes enabled.
    """
    for identifier_name, harness, issue_codes in registry.HARNESS_PRESETS:
        guides = tuple(ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE[code] for code in issue_codes)
        overhead = harness.calculate_prompt_overhead(guides, DEFAULT_VET_CONFIG)

        # Use the same limit as before for consistency
        assert overhead <= VET_MAX_PROMPT_TOKENS, (
            f"Prompt overhead for {identifier_name} is {overhead} tokens, "
            f"exceeds VET_MAX_PROMPT_TOKENS ({VET_MAX_PROMPT_TOKENS}). "
            f"Consider adjusting the limit or shortening prompts."
        )

        logger.info(f"{identifier_name}: {overhead} tokens")


def _make_guides_with_custom_suffix(
    issue_codes: tuple[IssueCode, ...],
    modified_code: IssueCode,
    suffix: str,
) -> tuple:
    """Apply a custom suffix override to one guide, returning all guides for the given issue codes."""
    override = CustomGuideOverride(issue_code=modified_code, suffix=suffix)
    return tuple(
        merge_guide_with_custom(
            ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE[code], override if code == modified_code else None
        )
        for code in issue_codes
    )


@pytest.mark.parametrize(
    "harness_type, issue_codes, modified_code",
    [
        (
            SinglePromptHarness,
            registry.ISSUE_CODES_FOR_BATCHED_COMMIT_CHECK,
            IssueCode.COMMIT_MESSAGE_MISMATCH,
        ),
        (
            ConversationSinglePromptHarness,
            registry.ISSUE_CODES_FOR_CONVERSATION_HISTORY_CHECK,
            IssueCode.MISLEADING_BEHAVIOR,
        ),
        (
            AgenticHarness,
            registry.ISSUE_CODES_FOR_BATCHED_COMMIT_CHECK + registry.ISSUE_CODES_FOR_CORRECTNESS_CHECK,
            IssueCode.LOGIC_ERROR,
        ),
    ],
    ids=["single_prompt", "conversation_single_prompt", "agentic"],
)
def test_prompt_overhead_reflects_guide_changes(
    harness_type: type,
    issue_codes: tuple[IssueCode, ...],
    modified_code: IssueCode,
) -> None:
    """
    Test that calculate_prompt_overhead reflects changes in guide content.

    Appends ~200 tokens of text to a single guide via custom suffix and verifies
    the overhead difference is in the expected range (100-400 tokens).
    """
    harness = harness_type()

    default_guides = tuple(ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE[code] for code in issue_codes)
    default_overhead = harness.calculate_prompt_overhead(default_guides, DEFAULT_VET_CONFIG)

    modified_guides = _make_guides_with_custom_suffix(issue_codes, modified_code, _CUSTOM_SUFFIX)
    modified_overhead = harness.calculate_prompt_overhead(modified_guides, DEFAULT_VET_CONFIG)

    diff = modified_overhead - default_overhead
    logger.info(
        f"{harness_type.__name__}: default={default_overhead}, " f"modified={modified_overhead}, diff={diff} tokens"
    )

    assert _CUSTOM_SUFFIX_TOKENS * 0.8 <= diff <= _CUSTOM_SUFFIX_TOKENS * 1.2, (
        f"Expected overhead difference of 100-400 tokens for ~200 token suffix, "
        f"but got {diff} tokens (default={default_overhead}, modified={modified_overhead})"
    )


AGENTIC_ISSUE_CODES = registry.ISSUE_CODES_FOR_BATCHED_COMMIT_CHECK + registry.ISSUE_CODES_FOR_CORRECTNESS_CHECK


def test_agentic_parallel_overhead_less_than_non_parallel() -> None:
    """
    Parallel mode uses one guide per prompt; non-parallel uses all guides in a
    single prompt. The per-request overhead in parallel mode should therefore be
    strictly less than non-parallel mode.
    """
    harness = AgenticHarness()
    guides = tuple(ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE[code] for code in AGENTIC_ISSUE_CODES)

    non_parallel_config = VetConfig(enable_parallel_agentic_issue_identification=False)
    parallel_config = VetConfig(enable_parallel_agentic_issue_identification=True)

    non_parallel_overhead = harness.calculate_prompt_overhead(guides, non_parallel_config)
    parallel_overhead = harness.calculate_prompt_overhead(guides, parallel_config)

    logger.info(f"Agentic non-parallel={non_parallel_overhead}, parallel={parallel_overhead} tokens")

    assert parallel_overhead <= non_parallel_overhead, (
        f"Expected parallel overhead ({parallel_overhead}) to be less than "
        f"non-parallel overhead ({non_parallel_overhead}), since parallel mode "
        f"uses a single guide per prompt instead of all guides."
    )


def test_agentic_parallel_overhead_reflects_guide_changes() -> None:
    """
    Test that parallel-mode overhead reflects changes in a single guide's content.

    In parallel mode each guide gets its own prompt, so modifying one guide
    should increase the max overhead when that guide's prompt is the largest.
    """
    config = VetConfig(enable_parallel_agentic_issue_identification=True)
    harness = AgenticHarness()

    default_guides = tuple(ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE[code] for code in AGENTIC_ISSUE_CODES)
    default_overhead = harness.calculate_prompt_overhead(default_guides, config)

    modified_overhead = max(
        harness.calculate_prompt_overhead(
            _make_guides_with_custom_suffix(AGENTIC_ISSUE_CODES, code, _CUSTOM_SUFFIX), config
        )
        for code in AGENTIC_ISSUE_CODES
    )

    diff = modified_overhead - default_overhead
    logger.info(f"Agentic parallel: default={default_overhead}, modified={modified_overhead}, diff={diff} tokens")

    assert _CUSTOM_SUFFIX_TOKENS * 0.8 <= diff <= _CUSTOM_SUFFIX_TOKENS * 1.2, (
        f"Expected overhead difference of {_CUSTOM_SUFFIX_TOKENS * 0.8:.0f}-{_CUSTOM_SUFFIX_TOKENS * 1.2:.0f} "
        f"tokens for ~{_CUSTOM_SUFFIX_TOKENS} token suffix, "
        f"but got {diff} tokens (default={default_overhead}, modified={modified_overhead})"
    )
