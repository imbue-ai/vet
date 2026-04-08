from vet.imbue_core.agents.agent_api.data_types import AgentAssistantMessage
from vet.imbue_core.agents.agent_api.data_types import AgentResultMessage
from vet.imbue_core.agents.agent_api.data_types import AgentSystemEventType
from vet.imbue_core.agents.agent_api.data_types import AgentSystemMessage
from vet.imbue_core.agents.agent_api.data_types import AgentTextBlock
from vet.imbue_core.agents.agent_api.data_types import AgentToolResultBlock
from vet.imbue_core.agents.agent_api.data_types import AgentToolUseBlock
from vet.imbue_core.agents.agent_api.gemini.message_parser import parse_gemini_event


class TestParseGeminiEvent:
    def test_parse_init_event(self) -> None:
        data = {
            "type": "init",
            "timestamp": "2026-04-08T19:41:49.957Z",
            "session_id": "2be756a5-ca2a-4023-853b-eb39e15bb9ef",
            "model": "auto-gemini-3",
        }
        message = parse_gemini_event(data)
        assert isinstance(message, AgentSystemMessage)
        assert message.event_type == AgentSystemEventType.SESSION_STARTED
        assert message.session_id == "2be756a5-ca2a-4023-853b-eb39e15bb9ef"

    def test_parse_message_event(self) -> None:
        data = {
            "type": "message",
            "timestamp": "2026-04-08T19:41:51.917Z",
            "role": "assistant",
            "content": "Hello world",
            "delta": True,
        }
        message = parse_gemini_event(data)
        assert isinstance(message, AgentAssistantMessage)
        assert len(message.content) == 1
        assert isinstance(message.content[0], AgentTextBlock)
        assert message.content[0].text == "Hello world"

    def test_parse_result_success_event(self) -> None:
        data = {
            "type": "result",
            "timestamp": "2026-04-08T19:41:52.092Z",
            "status": "success",
            "stats": {
                "total_tokens": 100,
                "input_tokens": 60,
                "output_tokens": 40,
                "cached": 10,
            },
        }
        message = parse_gemini_event(data, thread_id="test-session")
        assert isinstance(message, AgentResultMessage)
        assert message.is_error is False
        assert message.session_id == "test-session"
        assert message.usage is not None
        assert message.usage.total_tokens == 100
        assert message.usage.input_tokens == 60
        assert message.usage.output_tokens == 40
        assert message.usage.cached_tokens == 10

    def test_parse_result_error_event(self) -> None:
        data = {
            "type": "result",
            "timestamp": "2026-04-08T19:41:52.092Z",
            "status": "error",
            "error": "Something went wrong",
        }
        message = parse_gemini_event(data, thread_id="test-session")
        assert isinstance(message, AgentResultMessage)
        assert message.is_error is True
        assert message.error == "Something went wrong"
        assert message.session_id == "test-session"

    def test_parse_tool_use_event(self) -> None:
        data = {
            "type": "tool_use",
            "timestamp": "2026-04-08T19:41:52.092Z",
            "tool_name": "bash",
            "tool_id": "call_123",
            "parameters": {"command": "ls"},
        }
        message = parse_gemini_event(data)
        assert isinstance(message, AgentAssistantMessage)
        assert len(message.content) == 1
        tool_use = message.content[0]
        assert isinstance(tool_use, AgentToolUseBlock)
        assert tool_use.id == "call_123"
        assert tool_use.name == "bash"
        assert tool_use.input == {"command": "ls"}

    def test_parse_tool_result_event(self) -> None:
        data = {
            "type": "tool_result",
            "timestamp": "2026-04-08T19:41:52.092Z",
            "tool_id": "call_123",
            "output": "file1.txt\nfile2.txt",
            "status": "success",
        }
        message = parse_gemini_event(data)
        assert isinstance(message, AgentAssistantMessage)
        assert len(message.content) == 1
        tool_result = message.content[0]
        assert isinstance(tool_result, AgentToolResultBlock)
        assert tool_result.tool_use_id == "call_123"
        assert tool_result.content == "file1.txt\nfile2.txt"
        assert tool_result.is_error is False
