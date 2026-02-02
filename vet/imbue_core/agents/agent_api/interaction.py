from typing import Sequence

from vet.imbue_core.agents.agent_api.data_types import AgentAssistantMessage
from vet.imbue_core.agents.agent_api.data_types import AgentMessage
from vet.imbue_core.agents.agent_api.data_types import AgentOptions
from vet.imbue_core.agents.agent_api.data_types import AgentToolResultBlock
from vet.imbue_core.agents.agent_api.data_types import AgentToolUseBlock
from vet.imbue_core.agents.agent_api.data_types import AgentUserMessage
from vet.imbue_core.agents.agent_api.data_types import ToolUseRecord
from vet.imbue_core.pydantic_serialization import SerializableModel


class AgentInteraction:
    """A class for tracking an ongoing interaction with an agent.

    Note that this class is not thread-safe.
    """

    def __init__(self, prompt: str, options: AgentOptions) -> None:
        self.prompt = prompt
        self.options = options
        self.messages: list[AgentMessage] = []
        self.tool_use_records: list[ToolUseRecord] = []
        self._unresolved_tool_use_requests: list[AgentToolUseBlock] = []

    def put(self, message: AgentMessage) -> None:
        self.messages.append(message)

        if isinstance(message, AgentAssistantMessage):
            for assistant_content_block in message.content:
                if isinstance(assistant_content_block, AgentToolUseBlock):
                    self._unresolved_tool_use_requests.append(assistant_content_block)
        elif isinstance(message, AgentUserMessage) and isinstance(message.content, list):
            for content_block in message.content:
                if isinstance(content_block, AgentToolResultBlock):
                    remaining_unresolved_requests = []
                    for request in self._unresolved_tool_use_requests:
                        if request.id == content_block.tool_use_id:
                            self.tool_use_records.append(
                                ToolUseRecord(
                                    request_message=request,
                                    result_message=content_block,
                                )
                            )
                        else:
                            remaining_unresolved_requests.append(request)
                    self._unresolved_tool_use_requests = remaining_unresolved_requests

    def find_tool_use_record_by_command(self, command: str, by_most_recent: bool = True) -> ToolUseRecord | None:
        """Look for tool use request and result messages by the tool command.

        If by_most_recent is True, the records are searched in reverse order (most recent first).
        """
        return _find_tool_use_record_by_command(self.tool_use_records, command, by_most_recent)


class AgentInteractionRecord(SerializableModel):
    """A serializable record of a completed agent interaction.

    This is meant to be used for storing a completed log in a database or cache.
    """

    prompt: str
    options: AgentOptions
    messages: tuple[AgentMessage, ...]
    tool_use_records: tuple[ToolUseRecord, ...]

    @classmethod
    def from_agent_interaction(cls, agent_interaction: AgentInteraction) -> "AgentInteractionRecord":
        return cls(
            prompt=agent_interaction.prompt,
            options=agent_interaction.options,
            messages=tuple(agent_interaction.messages),
            tool_use_records=tuple(agent_interaction.tool_use_records),
        )

    def find_tool_use_record_by_command(self, command: str, by_most_recent: bool = True) -> ToolUseRecord | None:
        """Look for tool use request and result messages by the tool command.

        If by_most_recent is True, the records are searched in reverse order (most recent first).
        """
        return _find_tool_use_record_by_command(self.tool_use_records, command, by_most_recent)


def _find_tool_use_record_by_command(
    tool_use_records: Sequence[ToolUseRecord], command: str, reverse: bool = True
) -> ToolUseRecord | None:
    """Look for tool use request and result messages by the tool command.

    If reverse is True, the records are searched in reverse order (most recent first).
    """
    for record in reversed(tool_use_records) if reverse else tool_use_records:
        tool_input = record.tool_input
        if "command" in tool_input and tool_input["command"] == command:
            return record
    return None
