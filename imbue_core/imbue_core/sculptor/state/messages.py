import datetime
from enum import StrEnum
from typing import Annotated
from typing import Literal

from pydantic import Field
from pydantic import Tag

from imbue_core.agents.data_types.ids import AgentMessageID
from imbue_core.ids import AssistantMessageID
from imbue_core.pydantic_serialization import SerializableModel
from imbue_core.pydantic_serialization import build_discriminator
from imbue_core.sculptor.state.chat_state import ContentBlockTypes
from imbue_core.sculptor.telemetry import PosthogEventPayload
from imbue_core.sculptor.telemetry_constants import ConsentLevel
from imbue_core.sculptor.telemetry_utils import with_consent
from imbue_core.sculptor.telemetry_utils import without_consent
from imbue_core.time_utils import get_current_time


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
    Messages can come the AGENT (in-container LLM), USER (chat messages & direct interactions), SCULPTOR_SYSTEM (multifaceted sculptor app and service code) and RUNNER (the process controlling a task on the server.)
    """

    # Messages coming directly from the agent from inside the environment.
    AGENT = "AGENT"

    # Messages coming directly from a user interacting with the interface, ie chat
    USER = "USER"

    # Messages coming from sculptor-mediated actions and automations, like local sync updates or manual sync operations.
    # If there is ambiguity, (ie, "the user _did_ click a button but we did a lot of magic in the resolution") prefer SCULPTOR_SYSTEM.
    SCULPTOR_SYSTEM = "SCULPTOR_SYSTEM"

    # Messages coming from the task runner wrapper, such as environment shutdown.
    # conceptually a subset of SCULPTOR_SYSTEM
    RUNNER = "RUNNER"


class Message(SerializableModel):
    """Base class for all messages sent to or from the agent and user."""

    # used to dispatch and discover the type of message
    object_type: str
    # the unique ID of the message, used to track it across the system and prevent duplicates.
    # FIXME: get rid of the explicit passing of message_id
    message_id: AgentMessageID = Field(default_factory=AgentMessageID)
    # the source of the message, which can be either the agent, user, or runner.
    source: AgentMessageSource
    # roughly when the message was created, in UTC.
    # note that this is approximate due to clock skew -- these messages are created on different machines.
    # you should *not* sort by this field -- instead, rely on the order in which the messages are received.
    approximate_creation_time: datetime.datetime = Field(default_factory=get_current_time)

    # if the message is ephemeral, it will be logged but not saved to the database
    # if it is persistent, it will be logged AND saved to the database
    @property
    def is_ephemeral(self) -> bool:
        raise NotImplementedError("All messages must be subclassed off of PersistentMessage or EphemeralMessage")


class PersistentMessage(Message):
    @property
    def is_ephemeral(self) -> bool:
        return False


class PersistentUserMessage(PersistentMessage, PosthogEventPayload):
    """
    One of two base classes for messages sent from the user.
    Persistent user messages are saved to the database.
    Persistent user messages are queued in the task runner before they are sent to the agent.
    """

    # Override inherited fields with consent annotations
    # TODO (moishe): if other classes that derive from Message also start getting logged,
    # change the base Message class to derive from PosthogEventPayload. For now, doing
    # that is overkill and requires lots of annotations of irrelevant classes.
    #
    # TODO (mjr): We should really have `PersistentHoggableMessage` and `EphemeralHoggableMessage` or something
    object_type: str = without_consent(description="Type discriminator for user messages")
    message_id: AgentMessageID = without_consent(
        default_factory=AgentMessageID,
        description="Unique identifier for the user message",
    )
    source: AgentMessageSource = without_consent(default=AgentMessageSource.USER)
    approximate_creation_time: datetime.datetime = without_consent(
        default_factory=get_current_time,
        description="Approximate UTC timestamp when user message was created",
    )


class ChatInputUserMessage(PersistentUserMessage):
    object_type: str = without_consent(default="ChatInputUserMessage")
    text: str = with_consent(ConsentLevel.LLM_LOGS, description="User input text content")
    model_name: LLMModel = with_consent(
        ConsentLevel.PRODUCT_ANALYTICS,
        default=None,
        description="Selected LLM model for the chat request",
    )
    files: list[str] = with_consent(
        ConsentLevel.LLM_LOGS,
        default_factory=list,
        description="List of file paths (images, PDFs, etc., stored in Electron app folder) attached to this message",
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
