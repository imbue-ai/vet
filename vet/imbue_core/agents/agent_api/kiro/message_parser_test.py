from vet.imbue_core.agents.agent_api.data_types import AgentAssistantMessage
from vet.imbue_core.agents.agent_api.data_types import AgentResultMessage
from vet.imbue_core.agents.agent_api.data_types import AgentSystemEventType
from vet.imbue_core.agents.agent_api.data_types import AgentSystemMessage
from vet.imbue_core.agents.agent_api.data_types import AgentTextBlock
from vet.imbue_core.agents.agent_api.data_types import AgentThinkingBlock
from vet.imbue_core.agents.agent_api.data_types import AgentToolResultBlock
from vet.imbue_core.agents.agent_api.data_types import AgentToolUseBlock
from vet.imbue_core.agents.agent_api.data_types import AgentUnknownMessage
from vet.imbue_core.agents.agent_api.kiro.message_parser import parse_kiro_message


class TestParseResponses:
    def test_initialize_response_returns_none(self) -> None:
        data = {
            "jsonrpc": "2.0",
            "result": {
                "protocolVersion": 1,
                "agentCapabilities": {"loadSession": True},
                "agentInfo": {"name": "Kiro CLI Agent", "version": "2.11.1"},
            },
            "id": 0,
        }
        assert parse_kiro_message(data) is None

    def test_session_new_response_returns_system_message(self) -> None:
        data = {
            "jsonrpc": "2.0",
            "result": {
                "sessionId": "1629428e-2292-45b8-af1b-b11b01c105da",
                "modes": {"currentModeId": "kiro_default"},
                "models": {"currentModelId": "auto"},
            },
            "id": 1,
        }
        message = parse_kiro_message(data)
        assert isinstance(message, AgentSystemMessage)
        assert message.event_type == AgentSystemEventType.SESSION_STARTED
        assert message.session_id == "1629428e-2292-45b8-af1b-b11b01c105da"

    def test_prompt_turn_end_response_returns_none(self) -> None:
        # The client handles this directly (needs accumulated response text); the
        # parser leaves it alone so it isn't double-yielded.
        data = {"jsonrpc": "2.0", "result": {"stopReason": "end_turn"}, "id": 2}
        assert parse_kiro_message(data) is None

    def test_error_response_returns_error_result(self) -> None:
        data = {"jsonrpc": "2.0", "error": {"code": -32000, "message": "not authenticated"}, "id": 1}
        message = parse_kiro_message(data)
        assert isinstance(message, AgentResultMessage)
        assert message.is_error is True
        assert "not authenticated" in message.error


class TestParseAgentMessageChunk:
    def test_text_chunk_returns_assistant_message(self) -> None:
        data = {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "sess-1",
                "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "p"}},
            },
        }
        message = parse_kiro_message(data)
        assert isinstance(message, AgentAssistantMessage)
        assert len(message.content) == 1
        assert isinstance(message.content[0], AgentTextBlock)
        assert message.content[0].text == "p"

    def test_empty_text_chunk_returns_none(self) -> None:
        data = {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "sess-1",
                "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": ""}},
            },
        }
        assert parse_kiro_message(data) is None


class TestParseAgentThoughtChunk:
    def test_thought_chunk_returns_thinking_block(self) -> None:
        data = {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "sess-1",
                "update": {"sessionUpdate": "agent_thought_chunk", "content": {"type": "text", "text": "thinking..."}},
            },
        }
        message = parse_kiro_message(data)
        assert isinstance(message, AgentAssistantMessage)
        assert isinstance(message.content[0], AgentThinkingBlock)
        assert message.content[0].content == "thinking..."


class TestParseToolCall:
    def test_tool_call_returns_tool_use_block(self) -> None:
        data = {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "sess-1",
                "update": {
                    "sessionUpdate": "tool_call",
                    "toolCallId": "tooluse_hm149lLzlHE3jzlbX3rSvC",
                    "title": "Reading sample.txt:1",
                    "kind": "read",
                    "locations": [{"path": "sample.txt"}],
                    "rawInput": {
                        "operations": [{"mode": "Line", "path": "sample.txt"}],
                        "__tool_use_purpose": "Read sample.txt",
                    },
                    "_meta": {"kiro": {"toolName": "read"}},
                },
            },
        }
        message = parse_kiro_message(data)
        assert isinstance(message, AgentAssistantMessage)
        tool_use = message.content[0]
        assert isinstance(tool_use, AgentToolUseBlock)
        assert tool_use.id == "tooluse_hm149lLzlHE3jzlbX3rSvC"
        assert tool_use.name == "read"
        assert tool_use.input["operations"] == [{"mode": "Line", "path": "sample.txt"}]

    def test_tool_call_falls_back_to_kind_when_no_meta(self) -> None:
        data = {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "sess-1",
                "update": {
                    "sessionUpdate": "tool_call",
                    "toolCallId": "tooluse_abc",
                    "kind": "read",
                    "rawInput": {},
                },
            },
        }
        message = parse_kiro_message(data)
        tool_use = message.content[0]
        assert isinstance(tool_use, AgentToolUseBlock)
        assert tool_use.name == "read"


class TestParseToolCallUpdate:
    def test_completed_returns_tool_result_block(self) -> None:
        data = {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "sess-1",
                "update": {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": "tooluse_hm149lLzlHE3jzlbX3rSvC",
                    "kind": "read",
                    "status": "completed",
                    "rawOutput": {"items": [{"Text": "magic_number=42"}]},
                },
            },
        }
        message = parse_kiro_message(data)
        assert isinstance(message, AgentAssistantMessage)
        tool_result = message.content[0]
        assert isinstance(tool_result, AgentToolResultBlock)
        assert tool_result.tool_use_id == "tooluse_hm149lLzlHE3jzlbX3rSvC"
        assert tool_result.is_error is False
        assert "magic_number=42" in tool_result.content

    def test_failed_returns_error_tool_result_block(self) -> None:
        data = {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "sess-1",
                "update": {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": "tooluse_abc",
                    "kind": "execute",
                    "status": "failed",
                    "rawOutput": {"error": "command not found"},
                },
            },
        }
        message = parse_kiro_message(data)
        assert isinstance(message, AgentAssistantMessage)
        tool_result = message.content[0]
        assert isinstance(tool_result, AgentToolResultBlock)
        assert tool_result.tool_use_id == "tooluse_abc"
        assert tool_result.is_error is True
        assert "command not found" in tool_result.content

    def test_in_progress_returns_none(self) -> None:
        data = {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "sess-1",
                "update": {"sessionUpdate": "tool_call_update", "toolCallId": "tooluse_abc", "status": "in_progress"},
            },
        }
        assert parse_kiro_message(data) is None


class TestParseUnknown:
    def test_unknown_session_update_kind_returns_unknown_message(self) -> None:
        data = {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {"sessionId": "sess-1", "update": {"sessionUpdate": "some_future_kind"}},
        }
        message = parse_kiro_message(data)
        assert isinstance(message, AgentUnknownMessage)
        assert message.raw == data

    def test_private_kiro_notification_returns_none(self) -> None:
        data = {
            "jsonrpc": "2.0",
            "method": "_kiro.dev/subagent/list_update",
            "params": {"subagents": [], "pendingStages": []},
        }
        assert parse_kiro_message(data) is None

    def test_private_kiro_metadata_returns_none(self) -> None:
        data = {
            "jsonrpc": "2.0",
            "method": "_kiro.dev/metadata",
            "params": {"sessionId": "sess-1", "contextUsagePercentage": 6.29},
        }
        assert parse_kiro_message(data) is None

    def test_unknown_method_returns_unknown_message(self) -> None:
        data = {"jsonrpc": "2.0", "method": "session/some_future_method", "params": {}}
        message = parse_kiro_message(data)
        assert isinstance(message, AgentUnknownMessage)
        assert message.raw == data
