import pytest
from loguru import logger

from vet.imbue_core.data_types import IssueCode
from vet.imbue_tools.types.vet_config import VetConfig
from vet.issue_identifiers import registry
from vet.issue_identifiers.custom_guides import CustomGuideOverride
from vet.issue_identifiers.harnesses.conversation_single_prompt import ConversationSinglePromptHarness
from vet.issue_identifiers.harnesses.single_prompt import SinglePromptHarness
from vet.issue_identifiers.identification_guides import (
    ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE,
    merge_guide_with_custom,
)

DEFAULT_VET_CONFIG = VetConfig()

# 200 single-token words for testing overhead sensitivity.
_CUSTOM_SUFFIX = " ".join(["test"] * 200)
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
    ],
    ids=["single_prompt", "conversation_single_prompt"],
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

    assert 100 <= diff <= 400, (
        f"Expected overhead difference of 100-400 tokens for ~200 token suffix, "
        f"but got {diff} tokens (default={default_overhead}, modified={modified_overhead})"
    )
