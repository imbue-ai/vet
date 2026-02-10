from loguru import logger

from vet.imbue_tools.types.vet_config import VetConfig
from vet.issue_identifiers import registry
from vet.issue_identifiers.identification_guides import (
    ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE,
)
from vet.repo_utils import VET_MAX_PROMPT_TOKENS

DEFAULT_VET_CONFIG = VetConfig()


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
