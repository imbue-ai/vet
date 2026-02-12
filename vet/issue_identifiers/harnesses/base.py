import abc
from typing import Generic
from typing import TypeVar

from vet.imbue_tools.get_conversation_history.input_data_types import IdentifierInputs
from vet.issue_identifiers.base import IssueIdentifier
from vet.issue_identifiers.identification_guides import IssueIdentificationGuide

T = TypeVar("T", bound=IdentifierInputs)


class IssueIdentifierHarness(abc.ABC, Generic[T]):
    @abc.abstractmethod
    def make_issue_identifier(self, identification_guides: tuple[IssueIdentificationGuide, ...]) -> IssueIdentifier[T]:
        """Return an issue identifier based on this harness by binding it to the provided issue identification guides."""
