import json
from typing import Any

from vet.imbue_core.agents.agent_api.data_types import AgentAssistantMessage
from vet.imbue_core.agents.agent_api.data_types import AgentMessage
from vet.imbue_core.agents.agent_api.data_types import AgentResultMessage
from vet.imbue_core.agents.agent_api.data_types import AgentSystemEventType
from vet.imbue_core.agents.agent_api.data_types import AgentSystemMessage
from vet.imbue_core.agents.agent_api.data_types import AgentTextBlock
from vet.imbue_core.agents.agent_api.data_types import AgentThinkingBlock
from vet.imbue_core.agents.agent_api.data_types import AgentToolResultBlock
from vet.imbue_core.agents.agent_api.data_types import AgentToolUseBlock
from vet.imbue_core.agents.agent_api.data_types import AgentUnknownMessage


def parse_kiro_message(data: dict[str, Any]) -> AgentMessage | None:
    """Parse a single JSON-RPC line from `kiro-cli acp` into a normalized AgentMessage.

    Handles JSON-RPC responses (have "id") for session/new, and "session/update"
    notifications for streaming content. The initialize response and the prompt
    turn's terminal response (identified by "stopReason" in its result) are
    intentionally not turned into messages here -- the client handles both directly
    since it needs to correlate them with request ids and, for the terminal
    response, with accumulated response text. Kiro-private "_kiro.dev/*"
    notifications are dropped.
    """
    if "id" in data:
        if "result" in data:
            return _parse_response(data.get("result", {}), data)
        if "error" in data:
            return AgentResultMessage(session_id="", is_error=True, error=str(data["error"]), original_message=data)
        return None

    method = data.get("method", "")
    if method == "session/update":
        return _parse_session_update(data)

    if method.startswith("_kiro.dev/"):
        return None

    return AgentUnknownMessage(raw=data, original_message=data)


def _parse_response(result: dict[str, Any], data: dict[str, Any]) -> AgentMessage | None:
    if "sessionId" in result:
        return AgentSystemMessage(
            event_type=AgentSystemEventType.SESSION_STARTED,
            session_id=result["sessionId"],
            original_message=data,
        )
    # initialize response (has "agentInfo") and the prompt turn's terminal
    # response (has "stopReason") are both handled by the client, not here.
    return None


def _parse_session_update(data: dict[str, Any]) -> AgentMessage | None:
    update = data.get("params", {}).get("update", {})
    kind = update.get("sessionUpdate", "")

    if kind == "agent_message_chunk":
        text = update.get("content", {}).get("text", "")
        if not text:
            return None
        return AgentAssistantMessage(content=[AgentTextBlock(text=text)], original_message=data)

    if kind == "agent_thought_chunk":
        text = update.get("content", {}).get("text", "")
        if not text:
            return None
        return AgentAssistantMessage(content=[AgentThinkingBlock(content=text)], original_message=data)

    if kind == "tool_call":
        tool_name = update.get("_meta", {}).get("kiro", {}).get("toolName") or update.get("kind", "")
        return AgentAssistantMessage(
            content=[
                AgentToolUseBlock(
                    id=update.get("toolCallId", ""),
                    name=tool_name,
                    input=update.get("rawInput") or {},
                )
            ],
            original_message=data,
        )

    if kind == "tool_call_update":
        status = update.get("status")
        if status in ("pending", "in_progress"):
            return None
        raw_output = update.get("rawOutput")
        return AgentAssistantMessage(
            content=[
                AgentToolResultBlock(
                    tool_use_id=update.get("toolCallId", ""),
                    content=json.dumps(raw_output) if raw_output is not None else None,
                    is_error=status == "failed",
                )
            ],
            original_message=data,
        )

    return AgentUnknownMessage(raw=data, original_message=data)
