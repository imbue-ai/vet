from vet.imbue_core.data_types import IssueIdentifierType
from vet.imbue_core.frozen_utils import FrozenDict
from vet.imbue_core.itertools import first
from vet.imbue_tools.get_conversation_history.input_data_types import CommitInputs
from vet.imbue_tools.repo_utils.project_context import BaseProjectContext
from vet.imbue_tools.types.vet_config import VetConfig
from vet.issue_identifiers import registry
from vet.issue_identifiers.identification_guides import ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE
from vet.repo_utils import VET_MAX_PROMPT_TOKENS

EMPTY_PROJECT_CONTEXT = BaseProjectContext(file_contents_by_path=FrozenDict(), cached_prompt_prefix="")
DEFAULT_VET_CONFIG = VetConfig()


# Helper functions to extract a base prompt for different identifier types.
PROMPT_EXTRACTOR_FUNCTIONS = {
    IssueIdentifierType.BATCHED_COMMIT_CHECK: lambda identifier: identifier._get_prompt(
        EMPTY_PROJECT_CONTEXT,
        DEFAULT_VET_CONFIG,
        CommitInputs(maybe_goal="", maybe_diff=""),
    ),
    IssueIdentifierType.CORRECTNESS_COMMIT_CLASSIFIER: lambda identifier: identifier._get_prompt(
        EMPTY_PROJECT_CONTEXT,
        DEFAULT_VET_CONFIG,
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
            num_tokens <= VET_MAX_PROMPT_TOKENS
        ), f"Prompt for {identifier_name} exceeds VET_MAX_PROMPT_TOKENS. Consider increasing VET_MAX_PROMPT_TOKENS or shortening the prompt. "
