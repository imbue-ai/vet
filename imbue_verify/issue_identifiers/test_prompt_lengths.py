from imbue_core.data_types import IssueIdentifierType
from imbue_core.frozen_utils import FrozenDict
from imbue_core.itertools import first
from imbue_tools.get_conversation_history.input_data_types import CommitInputs
from imbue_tools.repo_utils.project_context import BaseProjectContext
from imbue_tools.types.imbue_verify_config import ImbueVerifyConfig
from imbue_verify.issue_identifiers import registry
from imbue_verify.issue_identifiers.identification_guides import (
    ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE,
)
from imbue_verify.repo_utils import IMBUE_VERIFY_MAX_PROMPT_TOKENS

EMPTY_PROJECT_CONTEXT = BaseProjectContext(file_contents_by_path=FrozenDict(), cached_prompt_prefix="")
DEFAULT_IMBUE_VERIFY_CONFIG = ImbueVerifyConfig()


# Helper functions to extract a base prompt for different identifier types.
PROMPT_EXTRACTOR_FUNCTIONS = {
    IssueIdentifierType.BATCHED_COMMIT_CHECK: lambda identifier: identifier._get_prompt(
        EMPTY_PROJECT_CONTEXT,
        DEFAULT_IMBUE_VERIFY_CONFIG,
        CommitInputs(maybe_goal="", maybe_diff=""),
    ),
    IssueIdentifierType.CORRECTNESS_COMMIT_CLASSIFIER: lambda identifier: identifier._get_prompt(
        EMPTY_PROJECT_CONTEXT,
        DEFAULT_IMBUE_VERIFY_CONFIG,
        CommitInputs(maybe_goal="", maybe_diff=""),
    ),
}


def _estimate_tokens(prompt: str) -> int:
    """
    Estimate the number of tokens in a prompt.
    This is a rough estimate and may not be accurate for all models.
    """
    # A factor of 1/4.5 appears to be a reasonable empirical estimate for current models.
    # We use a slighly larger factor (1/4) to have a more conservative estimate.
    return round(len(prompt) / 4)


def test_prompt_lengths() -> None:
    """
    Test that the prompt lengths for various issue identifiers do not exceed the maximum allowed length.
    This is important to ensure that the LLM can process the prompts without raising errors.
    """

    for identifier_name, extract_prompt in PROMPT_EXTRACTOR_FUNCTIONS.items():
        identifier = first(
            [
                harness.make_issue_identifier(tuple(ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE[c] for c in codes))
                for name, harness, codes in registry.HARNESS_PRESETS
                if name == identifier_name
            ]
        )
        prompt = extract_prompt(identifier)
        num_tokens = _estimate_tokens(prompt)
        assert (
            num_tokens <= IMBUE_VERIFY_MAX_PROMPT_TOKENS
        ), f"Prompt for {identifier_name} exceeds IMBUE_VERIFY_MAX_PROMPT_TOKENS. Consider increasing IMBUE_VERIFY_MAX_PROMPT_TOKENS or shortening the prompt. "
