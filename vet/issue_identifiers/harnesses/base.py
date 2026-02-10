import abc
from typing import Generic
from typing import TypeVar

from vet.imbue_tools.get_conversation_history.input_data_types import IdentifierInputs
from vet.imbue_tools.types.vet_config import VetConfig
from vet.issue_identifiers.base import IssueIdentifier
from vet.issue_identifiers.identification_guides import (
    IssueIdentificationGuide,
)

T = TypeVar("T", bound=IdentifierInputs)


class IssueIdentifierHarness(abc.ABC, Generic[T]):
    @abc.abstractmethod
    def make_issue_identifier(self, identification_guides: tuple[IssueIdentificationGuide, ...]) -> IssueIdentifier[T]:
        """Return an issue identifier based on this harness by binding it to the provided issue identification guides."""

    @abc.abstractmethod
    def calculate_prompt_overhead(
        self,
        identification_guides: tuple[IssueIdentificationGuide, ...],
        config: VetConfig,
    ) -> int:
        """
        Calculate the token overhead for this harness with the given guides.

        This includes:
        - Static instruction text and templates
        - Issue identification guides formatted for LLM
        - Response schema
        - Any other fixed prompt components

        Excludes dynamic content like diff, goal, conversation history, etc.

        Args:
            identification_guides: The issue guides this harness will use
            config: VetConfig to access language model for token counting

        Returns:
            Number of tokens used by the prompt overhead
        """
