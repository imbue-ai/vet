"""Message types for Vet conversation history.

These are simplified versions that avoid dependencies on external telemetry libraries.
"""

import datetime
from enum import StrEnum
from typing import Annotated
from typing import Literal

from pydantic import Field
from pydantic import Tag

from vet.imbue_core.pydantic_serialization import SerializableModel
from vet.imbue_core.pydantic_serialization import build_discriminator
from vet.imbue_core.time_utils import get_current_time
from vet.vet_types.chat_state import ContentBlockTypes
from vet.vet_types.ids import AgentMessageID
from vet.vet_types.ids import AssistantMessageID


class LLMModel(StrEnum):
    CLAUDE_4_OPUS = "CLAUDE-4-OPUS"
    CLAUDE_4_SONNET = "CLAUDE-4-SONNET"
    CLAUDE_4_HAIKU = "CLAUDE-4-HAIKU"
    GPT_5_1_CODEX = "GPT-5.1-CODEX"
    GPT_5_1_CODEX_MINI = "GPT-5.1-CODEX-MINI"
    GPT_5_1 = "GPT-5.1"
    GPT_5_2 = "GPT-5.2"


# ==================================
# Backend Message Type Definitions
# ==================================


class AgentMessageSource(StrEnum):
    """
    Messages can come from the AGENT (LLM), USER (chat messages & direct interactions),
    SYSTEM (app and service code) and RUNNER (the process controlling a task).
    """

    # Messages coming directly from the agent.
    AGENT = "AGENT"

    # Messages coming directly from a user interacting with the interface, ie chat.
    USER = "USER"

    # Messages coming from system-mediated actions and automations.
    SYSTEM = "SYSTEM"

    # Messages coming from the task runner wrapper, such as environment shutdown.
    RUNNER = "RUNNER"


class Message(SerializableModel):
    """Base class for all messages sent to or from the agent and user."""

    # used to dispatch and discover the type of message
    object_type: str
    # the unique ID of the message, used to track it across the system and prevent duplicates.
    message_id: AgentMessageID = Field(default_factory=AgentMessageID)
    # the source of the message, which can be either the agent, user, or runner.
    source: AgentMessageSource
    # roughly when the message was created, in UTC.
    approximate_creation_time: datetime.datetime = Field(default_factory=get_current_time)

    @property
    def is_ephemeral(self) -> bool:
        raise NotImplementedError("All messages must be subclassed off of PersistentMessage or EphemeralMessage")


class PersistentMessage(Message):
    @property
    def is_ephemeral(self) -> bool:
        return False


class PersistentUserMessage(PersistentMessage):
    """
    One of two base classes for messages sent from the user.
    Persistent user messages are saved to the database.
    """

    object_type: str = Field(
        default="PersistentUserMessage",
        description="Type discriminator for user messages",
    )
    message_id: AgentMessageID = Field(
        default_factory=AgentMessageID,
        description="Unique identifier for the user message",
    )
    source: AgentMessageSource = Field(default=AgentMessageSource.USER)
    approximate_creation_time: datetime.datetime = Field(
        default_factory=get_current_time,
        description="Approximate UTC timestamp when user message was created",
    )


class ChatInputUserMessage(PersistentUserMessage):
    object_type: str = Field(default="ChatInputUserMessage")
    text: str = Field(..., description="User input text content")
    model_name: LLMModel | None = Field(
        default=None,
        description="Selected LLM model for the chat request",
    )
    files: list[str] = Field(
        default_factory=list,
        description="List of file paths attached to this message",
    )


class PersistentAgentMessage(PersistentMessage):
    """Base class for messages sent from the agent."""

    source: AgentMessageSource = AgentMessageSource.AGENT


class ResponseBlockAgentMessage(PersistentAgentMessage):
    object_type: str = "ResponseBlockAgentMessage"
    role: Literal["user", "assistant", "system"]
    assistant_message_id: AssistantMessageID
    content: tuple[ContentBlockTypes, ...]


ConversationMessageUnion = Annotated[
    Annotated[ResponseBlockAgentMessage, Tag("ResponseBlockAgentMessage")]
    | Annotated[ChatInputUserMessage, Tag("ChatInputUserMessage")],
    build_discriminator(),
]
