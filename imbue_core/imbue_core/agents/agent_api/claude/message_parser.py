from typing import Any
from typing import assert_never

from imbue_core.agents.agent_api.data_types import AgentAssistantMessage
from imbue_core.agents.agent_api.data_types import AgentContentBlock
from imbue_core.agents.agent_api.data_types import AgentMessage
from imbue_core.agents.agent_api.data_types import AgentResultMessage
from imbue_core.agents.agent_api.data_types import AgentSystemEventType
from imbue_core.agents.agent_api.data_types import AgentSystemMessage
from imbue_core.agents.agent_api.data_types import AgentTextBlock
from imbue_core.agents.agent_api.data_types import AgentThinkingBlock
from imbue_core.agents.agent_api.data_types import AgentToolResultBlock
from imbue_core.agents.agent_api.data_types import AgentToolUseBlock
from imbue_core.agents.agent_api.data_types import AgentUsage
from imbue_core.agents.agent_api.data_types import AgentUserMessage


def parse_claude_message(data: dict[str, Any]) -> AgentMessage | None:
    """Parse message from CLI output using unified types.

    Reference:
    https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/_internal/message_parser.py
    https://docs.claude.com/en/api/agent-sdk/typescript#sdkmessage
    https://docs.claude.com/en/api/agent-sdk/python#message-types
    """

    match data["type"]:
        case "user":
            return AgentUserMessage(content=parse_claude_content_blocks(data), original_message=data)

        case "assistant":
            return AgentAssistantMessage(content=parse_claude_content_blocks(data), original_message=data)

        case "system":
            # Normalize system event types
            event_type = parse_claude_system_event_type(data.get("subtype", ""))
            return AgentSystemMessage(
                event_type=event_type,
                session_id=data.get("session_id"),
                error=data.get("error"),
                original_message=data,
            )

        case "result":
            # Build normalized usage
            usage = None
            raw_usage = data.get("usage")
            if raw_usage or data.get("total_cost_usd"):
                usage = AgentUsage(
                    input_tokens=raw_usage.get("input_tokens") if raw_usage else None,
                    output_tokens=raw_usage.get("output_tokens") if raw_usage else None,
                    cached_tokens=raw_usage.get("cache_read_input_tokens") if raw_usage else None,
                    total_tokens=(
                        raw_usage.get("input_tokens", 0) + raw_usage.get("output_tokens", 0) if raw_usage else None
                    ),
                    total_cost_usd=data.get("total_cost_usd"),
                )

            return AgentResultMessage(
                session_id=data["session_id"],
                is_error=data["is_error"],
                duration_ms=data.get("duration_ms"),
                api_duration_ms=data.get("duration_api_ms"),
                num_turns=data.get("num_turns"),
                usage=usage,
                result=data.get("result"),
                error=data.get("error") if data["is_error"] else None,
                original_message=data,
            )

        case _ as unreachable:
            assert_never(unreachable)


def parse_claude_system_event_type(subtype: str) -> AgentSystemEventType:
    """Parse Claude system event subtype to unified event type."""
    subtype_lower = subtype.lower()

    # TODO add other system event types as we find them
    #  basically the documentattion doesn't mention any other system event types
    #  other than init AFAIKT
    if "init" in subtype_lower:
        return AgentSystemEventType.SESSION_STARTED
    else:
        return AgentSystemEventType.OTHER


def parse_claude_content_blocks(data: dict[str, Any]) -> list[AgentContentBlock]:
    return [parse_claude_content_block(block) for block in data["message"]["content"]]


def parse_claude_content_block(block: dict[str, Any]) -> AgentContentBlock:
    """Parse content block from CLI output using unified types."""

    match block["type"]:
        case "text":
            return AgentTextBlock(text=block["text"])

        case "thinking":
            # Claude Code thinking blocks
            return AgentThinkingBlock(
                content=block.get("thinking", ""),
                thinking_tokens=block.get("thinking_tokens"),
            )

        case "tool_use":
            return AgentToolUseBlock(id=block["id"], name=block["name"], input=block["input"])

        case "tool_result":
            return AgentToolResultBlock(
                tool_use_id=block["tool_use_id"],
                content=block.get("content"),
                is_error=block.get("is_error"),
            )

        case _ as unreachable:
            assert_never(unreachable)
