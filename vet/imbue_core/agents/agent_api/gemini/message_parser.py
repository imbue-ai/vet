"""Message parsing for Gemini CLI agent."""

from typing import Any
from typing import assert_never

from loguru import logger
from pydantic import TypeAdapter
from pydantic import ValidationError

from vet.imbue_core.agents.agent_api.data_types import AgentAssistantMessage
from vet.imbue_core.agents.agent_api.data_types import AgentMessage
from vet.imbue_core.agents.agent_api.data_types import AgentResultMessage
from vet.imbue_core.agents.agent_api.data_types import AgentSystemEventType
from vet.imbue_core.agents.agent_api.data_types import AgentSystemMessage
from vet.imbue_core.agents.agent_api.data_types import AgentTextBlock
from vet.imbue_core.agents.agent_api.data_types import AgentUnknownMessage
from vet.imbue_core.agents.agent_api.data_types import AgentUsage
from vet.imbue_core.agents.agent_api.gemini.data_types import GeminiInitEvent
from vet.imbue_core.agents.agent_api.gemini.data_types import GeminiMessageEvent
from vet.imbue_core.agents.agent_api.gemini.data_types import GeminiResultEvent
from vet.imbue_core.agents.agent_api.gemini.data_types import GeminiStreamEventUnion
from vet.imbue_core.agents.agent_api.gemini.data_types import GeminiToolResultEvent
from vet.imbue_core.agents.agent_api.gemini.data_types import GeminiToolUseEvent


def parse_gemini_event(data: dict[str, Any], thread_id: str | None = None) -> AgentMessage:
    """Parse Gemini stream event into unified message."""
    try:
        gemini_event = TypeAdapter(GeminiStreamEventUnion).validate_python(data)
    except ValidationError as e:
        logger.debug("Failed to parse Gemini event: {error}. Data: {data}", error=e, data=data)
        return AgentUnknownMessage(raw=data, original_message=data)

    match gemini_event:
        case GeminiInitEvent():
            return AgentSystemMessage(
                event_type=AgentSystemEventType.SESSION_STARTED,
                session_id=gemini_event.session_id,
                original_message=data,
            )

        case GeminiMessageEvent():
            if gemini_event.role == "assistant":
                # We map message chunks to AgentAssistantMessage text blocks
                return AgentAssistantMessage(
                    content=[AgentTextBlock(text=gemini_event.content)],
                    original_message=data,
                )
            return AgentUnknownMessage(raw=data, original_message=data)

        case GeminiResultEvent():
            session_id = thread_id or "unknown"
            if gemini_event.status == "error":
                return AgentResultMessage(
                    session_id=session_id,
                    is_error=True,
                    error=gemini_event.error or "Unknown Gemini CLI error",
                    usage=None,
                    original_message=data,
                )

            usage = None
            if gemini_event.stats:
                usage = AgentUsage(
                    input_tokens=gemini_event.stats.input_tokens,
                    output_tokens=gemini_event.stats.output_tokens,
                    cached_tokens=gemini_event.stats.cached,
                    total_tokens=gemini_event.stats.total_tokens,
                )

            return AgentResultMessage(
                session_id=session_id,
                is_error=False,
                usage=usage,
                original_message=data,
            )

        case GeminiToolUseEvent():
            # Not fully supported in schema yet, but returning it as unknown for now
            return AgentUnknownMessage(raw=data, original_message=data)

        case GeminiToolResultEvent():
            return AgentUnknownMessage(raw=data, original_message=data)

        case _ as unreachable:
            assert_never(unreachable)
