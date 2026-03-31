from vet.imbue_core.agents.agent_api.codex.message_parser import parse_codex_event
from vet.imbue_core.agents.agent_api.data_types import AgentAssistantMessage
from vet.imbue_core.agents.agent_api.data_types import AgentToolResultBlock
from vet.imbue_core.agents.agent_api.data_types import AgentToolUseBlock


class TestParseCollabToolCall:
    def test_item_started_returns_tool_use_block(self) -> None:
        data = {
            "type": "item.started",
            "item": {
                "id": "item_38",
                "type": "collab_tool_call",
                "tool": "spawn_agent",
                "sender_thread_id": "thread_parent",
                "receiver_thread_ids": [],
                "prompt": "Review the diff",
                "agents_states": {},
                "status": "in_progress",
            },
        }

        message = parse_codex_event(data, "thread_parent")

        assert isinstance(message, AgentAssistantMessage)
        assert len(message.content) == 1
        tool_use = message.content[0]
        assert isinstance(tool_use, AgentToolUseBlock)
        assert tool_use.id == "item_38"
        assert tool_use.name == "spawn_agent"
        assert tool_use.input == {
            "tool": "spawn_agent",
            "sender_thread_id": "thread_parent",
            "receiver_thread_ids": [],
            "prompt": "Review the diff",
            "agents_states": {},
        }

    def test_item_completed_returns_tool_result_block(self) -> None:
        data = {
            "type": "item.completed",
            "item": {
                "id": "item_38",
                "type": "collab_tool_call",
                "tool": "spawn_agent",
                "sender_thread_id": "thread_parent",
                "receiver_thread_ids": ["thread_child"],
                "prompt": "Review the diff",
                "agents_states": {"thread_child": {"status": "completed"}},
                "status": "completed",
            },
        }

        message = parse_codex_event(data, "thread_parent")

        assert isinstance(message, AgentAssistantMessage)
        assert len(message.content) == 1
        tool_result = message.content[0]
        assert isinstance(tool_result, AgentToolResultBlock)
        assert tool_result.tool_use_id == "item_38"
        assert tool_result.content == [
            {
                "tool": "spawn_agent",
                "sender_thread_id": "thread_parent",
                "receiver_thread_ids": ["thread_child"],
                "prompt": "Review the diff",
                "agents_states": {"thread_child": {"status": "completed"}},
            }
        ]
        assert tool_result.is_error is False
        assert tool_result.exit_code == 0
