from typing import Any
from typing import assert_never

from pydantic import TypeAdapter

from imbue_core.agents.agent_api.codex.data_types import CodexAgentMessageItem
from imbue_core.agents.agent_api.codex.data_types import CodexCommandExecutionItem
from imbue_core.agents.agent_api.codex.data_types import CodexErrorItem
from imbue_core.agents.agent_api.codex.data_types import CodexFileChangeItem
from imbue_core.agents.agent_api.codex.data_types import CodexItemCompletedEvent
from imbue_core.agents.agent_api.codex.data_types import CodexItemStartedEvent
from imbue_core.agents.agent_api.codex.data_types import CodexItemUpdatedEvent
from imbue_core.agents.agent_api.codex.data_types import CodexMcpToolCallItem
from imbue_core.agents.agent_api.codex.data_types import CodexReasoningItem
from imbue_core.agents.agent_api.codex.data_types import CodexThreadErrorEvent
from imbue_core.agents.agent_api.codex.data_types import CodexThreadEvent
from imbue_core.agents.agent_api.codex.data_types import CodexThreadItemUnion
from imbue_core.agents.agent_api.codex.data_types import CodexThreadStartedEvent
from imbue_core.agents.agent_api.codex.data_types import CodexTodoListItem
from imbue_core.agents.agent_api.codex.data_types import CodexTurnCompletedEvent
from imbue_core.agents.agent_api.codex.data_types import CodexTurnFailedEvent
from imbue_core.agents.agent_api.codex.data_types import CodexTurnStartedEvent
from imbue_core.agents.agent_api.codex.data_types import CodexWebSearchItem
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


def parse_codex_event(
    data: dict[str, Any], thread_id: str | None = None
) -> AgentMessage | None:
    """Parse Codex event into unified message.

    Reference:
    https://github.com/openai/codex/blob/main/docs/exec.md
    https://github.com/openai/codex/blob/main/sdk/typescript/src/events.ts
    """
    codex_event = TypeAdapter(CodexThreadEvent).validate_python(data)
    match codex_event:
        case CodexThreadStartedEvent():
            return AgentSystemMessage(
                event_type=AgentSystemEventType.SESSION_STARTED,
                session_id=codex_event.thread_id,
                original_message=data,
            )

        case CodexTurnStartedEvent():
            # Turn started within a thread. Nothing to do
            return None

        case CodexTurnCompletedEvent():
            assert (
                thread_id is not None
            ), "thread_id is required for turn.completed event"
            usage = AgentUsage(
                input_tokens=codex_event.usage.input_tokens,
                output_tokens=codex_event.usage.output_tokens,
                cached_tokens=codex_event.usage.cached_input_tokens,
                total_tokens=codex_event.usage.input_tokens
                + codex_event.usage.output_tokens,
            )
            return AgentResultMessage(
                session_id=thread_id,
                is_error=False,
                usage=usage,
                original_message=data,
            )

        case CodexTurnFailedEvent():
            assert thread_id is not None, "thread_id is required for turn.failed event"
            return AgentResultMessage(
                session_id=thread_id,
                is_error=True,
                error=codex_event.error.message,
                usage=None,
                original_message=data,
            )

        case CodexItemStartedEvent():
            content_blocks = parse_codex_item(codex_event.item)
            return AgentAssistantMessage(content=content_blocks, original_message=data)

        case CodexItemUpdatedEvent():
            # Intermediate item, don't return anything
            return None

        case CodexItemCompletedEvent():
            content_blocks = parse_codex_item(codex_event.item)
            return AgentAssistantMessage(content=content_blocks, original_message=data)

        case CodexThreadErrorEvent():
            return AgentResultMessage(
                session_id=thread_id or "",
                is_error=True,
                error=codex_event.message,
                usage=None,
                original_message=data,
            )
        case _ as unreachable:
            assert_never(unreachable)


def parse_codex_item(
    item_data: dict[str, Any] | CodexThreadItemUnion,
) -> list[AgentContentBlock]:
    """Parse Codex item into unified content blocks.

    Refs:
    https://github.com/openai/codex/blob/main/sdk/typescript/src/items.ts
    """
    if isinstance(item_data, dict):
        codex_item = TypeAdapter(CodexThreadItemUnion).validate_python(item_data)
    else:
        codex_item = item_data

    match codex_item:
        case CodexAgentMessageItem():
            return [AgentTextBlock(text=codex_item.text)]

        case CodexReasoningItem():
            return [AgentThinkingBlock(content=codex_item.text)]

        case CodexErrorItem():
            return [AgentTextBlock(text=f"[Error: {codex_item.message}]")]

        case CodexCommandExecutionItem():
            if codex_item.status == "in_progress":
                return [
                    AgentToolUseBlock(
                        id=codex_item.id,
                        name=codex_item.type,
                        input={"command": codex_item.command},
                    )
                ]
            return [
                AgentToolResultBlock(
                    tool_use_id=codex_item.id,
                    content=codex_item.aggregated_output,
                    exit_code=codex_item.exit_code,
                    is_error=codex_item.exit_code != 0,
                )
            ]

        case CodexFileChangeItem():
            is_error = codex_item.status == "failed"
            return [
                AgentToolUseBlock(
                    id=codex_item.id,
                    name=codex_item.type,
                    input={
                        "changes": [
                            change.model_dump() for change in codex_item.changes
                        ]
                    },
                ),
                AgentToolResultBlock(
                    tool_use_id=codex_item.id,
                    content=[change.model_dump() for change in codex_item.changes],
                    is_error=is_error,
                    exit_code=-1 if is_error else 0,
                ),
            ]

        case CodexMcpToolCallItem():
            if codex_item.status == "in_progress":
                return [
                    AgentToolUseBlock(
                        id=codex_item.id,
                        name=codex_item.type,
                        input={"server": codex_item.server, "tool": codex_item.tool},
                    )
                ]
            # NOTE: currently (24-oct-2025) the MCP tool call item is not really well defined
            # it does not have a result field or anything. So for now, we just return the server and tool as the content.
            return [
                AgentToolResultBlock(
                    tool_use_id=codex_item.id,
                    content=[{"server": codex_item.server, "tool": codex_item.tool}],
                    is_error=codex_item.status == "failed",
                    exit_code=-1 if codex_item.status == "failed" else 0,
                )
            ]

        case CodexWebSearchItem():
            # NOTE: currently (24-oct-2025) the web search item is not really well defined
            # i.e. it only has a query field, and no other fields like results, progress, etc.
            # so for now, so that each tool use has a matching result, we just return the query as the content.
            return [
                AgentToolUseBlock(
                    id=codex_item.id,
                    name=codex_item.type,
                    input={"query": codex_item.query},
                ),
                AgentToolResultBlock(
                    tool_use_id=codex_item.id,
                    content=codex_item.query,
                    # No error reported for web search
                    is_error=False,
                    exit_code=0,
                ),
            ]

        case CodexTodoListItem():
            return [
                AgentToolUseBlock(
                    id=codex_item.id,
                    name=codex_item.type,
                    input={"todos": [item.model_dump() for item in codex_item.items]},
                ),
                AgentToolResultBlock(
                    tool_use_id=codex_item.id,
                    content=[item.model_dump() for item in codex_item.items],
                    is_error=False,
                    exit_code=0,
                ),
            ]

        case _ as unreachable:
            assert_never(unreachable)
