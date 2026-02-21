from typing import Any

from vet.imbue_core.agents.agent_api.data_types import AgentAssistantMessage
from vet.imbue_core.agents.agent_api.data_types import AgentContentBlock
from vet.imbue_core.agents.agent_api.data_types import AgentMessage
from vet.imbue_core.agents.agent_api.data_types import AgentResultMessage
from vet.imbue_core.agents.agent_api.data_types import AgentSystemEventType
from vet.imbue_core.agents.agent_api.data_types import AgentSystemMessage
from vet.imbue_core.agents.agent_api.data_types import AgentTextBlock
from vet.imbue_core.agents.agent_api.data_types import AgentToolResultBlock
from vet.imbue_core.agents.agent_api.data_types import AgentToolUseBlock
from vet.imbue_core.agents.agent_api.data_types import AgentUnknownMessage
from vet.imbue_core.agents.agent_api.data_types import AgentUsage


def parse_opencode_event(data: dict[str, Any]) -> AgentMessage | None:
    """Parse OpenCode JSON event into unified message type.

    Reference: `opencode run --format json`

    OpenCode emits JSONL events with these top-level types:
    - step_start: a new agent step begins
    - text: agent text output
    - tool_use: tool invocation with input/output (state includes completed results)
    - step_finish: step completed with cost/token info and reason (stop, tool-calls)
    """
    event_type = data.get("type", "")
    part = data.get("part", {})
    session_id = data.get("sessionID", "")

    match event_type:
        case "step_start":
            return AgentSystemMessage(
                event_type=AgentSystemEventType.SESSION_STARTED,
                session_id=session_id,
                original_message=data,
            )

        case "text":
            text = part.get("text", "")
            return AgentAssistantMessage(
                content=[AgentTextBlock(text=text)],
                original_message=data,
            )

        case "tool_use":
            content_blocks = _parse_tool_use_part(part)
            return AgentAssistantMessage(
                content=content_blocks,
                original_message=data,
            )

        case "step_finish":
            return _parse_step_finish(data, part, session_id)

        case _:
            return AgentUnknownMessage(raw=data, original_message=data)


def _parse_tool_use_part(part: dict[str, Any]) -> list[AgentContentBlock]:
    """Parse tool_use event part into content blocks.

    OpenCode tool_use events contain both the tool invocation and its result
    (when status is "completed") in a single event.
    """
    state = part.get("state", {})
    tool_name = part.get("tool", "unknown")
    call_id = part.get("callID", part.get("id", ""))
    tool_input = state.get("input", {})

    content_blocks: list[AgentContentBlock] = []

    # Tool use request
    content_blocks.append(
        AgentToolUseBlock(
            id=call_id,
            name=tool_name,
            input=tool_input,
        )
    )

    # If the tool has completed, also emit a result block
    if state.get("status") == "completed":
        output = state.get("output", "")
        metadata = state.get("metadata", {})
        exit_code = metadata.get("exit") if metadata else None
        content_blocks.append(
            AgentToolResultBlock(
                tool_use_id=call_id,
                content=output,
                is_error=exit_code is not None and exit_code != 0,
                exit_code=exit_code,
            )
        )

    return content_blocks


def _parse_step_finish(
    data: dict[str, Any], part: dict[str, Any], session_id: str
) -> AgentMessage:
    """Parse step_finish event.

    A step_finish with reason="stop" is the final result message.
    A step_finish with reason="tool-calls" is an intermediate system event.
    """
    tokens_data = part.get("tokens")
    usage = None
    if tokens_data:
        cache = tokens_data.get("cache", {})
        usage = AgentUsage(
            input_tokens=tokens_data.get("input"),
            output_tokens=tokens_data.get("output"),
            cached_tokens=cache.get("read") if cache else None,
            total_tokens=tokens_data.get("total"),
            thinking_tokens=tokens_data.get("reasoning") or None,
            total_cost_usd=part.get("cost"),
        )

    reason = part.get("reason", "")
    is_final = reason == "stop"

    if is_final:
        return AgentResultMessage(
            session_id=session_id,
            is_error=False,
            usage=usage,
            original_message=data,
        )

    # Non-final step_finish (e.g., reason="tool-calls") -> system event
    return AgentSystemMessage(
        event_type=AgentSystemEventType.TURN_COMPLETED,
        session_id=session_id,
        original_message=data,
    )
