import abc
from typing import Generator
from typing import Generic
from typing import TypeVar

from vet.imbue_core.data_types import IssueCode
from vet.imbue_core.data_types import IssueIdentificationDebugInfo
from vet.imbue_core.pydantic_serialization import SerializableModel
from vet.imbue_tools.get_conversation_history.input_data_types import IdentifierInputs
from vet.imbue_tools.get_conversation_history.input_data_types import (
    to_specific_inputs_type,
)
from vet.imbue_tools.repo_utils.project_context import ProjectContext
from vet.imbue_tools.types.vet_config import VetConfig
from vet.issue_identifiers.common import GeneratedIssueSchema

T = TypeVar("T", bound=IdentifierInputs)


class IssueIdentifier(SerializableModel, abc.ABC, Generic[T]):
    """
    A protocol for identifying issues given certain inputs.

    By implementing this protocol and registering the new instance in `vet/issue_identifiers/registry.py`,
    one can create a new issue identifier and automatically expand the default abilities of vet.

    """

    @abc.abstractmethod
    def identify_issues(
        self,
        identifier_inputs: T,
        project_context: ProjectContext,
        config: VetConfig,
    ) -> Generator[GeneratedIssueSchema, None, IssueIdentificationDebugInfo]:
        """
        Identify issues given the identifier inputs.

        Args:
            identifier_inputs: The inputs which determine the content provided to the identifier.
            project_context: Loaded data corresponding to the inputs, e.g. diffs or files.
            config: Settings

        Returns:
            A generator of identified issues. When done iterating, returns the debug info.

        Raises:
            IdentifierInputsMissingError: If the identifier inputs are missing required information for this identifier.
        """

    @abc.abstractmethod
    def input_type(self) -> type[T]:
        """
        The type of inputs that this identifier expects.
        """

    def to_required_inputs(self, identifier_inputs: IdentifierInputs) -> T:
        return to_specific_inputs_type(identifier_inputs, self.input_type())

    @property
    @abc.abstractmethod
    def enabled_issue_codes(self) -> tuple[IssueCode, ...]:
        """
        The issue codes that this identifier is capable of identifying.
        """

    @property
    def requires_agentic_collation(self) -> bool:
        """
        Whether this identifier requires agentic collation of issues.
        """
        return False

    @property
    @abc.abstractmethod
    def identifies_code_issues(self) -> bool:
        """
        Whether this identifier identifies code-related issues (as opposed to e.g. conversation-related issues).
        """
        pass

    @abc.abstractmethod
    def _get_prompt(
        self,
        project_context: ProjectContext,
        config: VetConfig,
        identifier_inputs: T,
    ) -> str:
        """
        Get the prompt for this identifier.
        """
        pass
