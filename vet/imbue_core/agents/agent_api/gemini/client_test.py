import json
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from vet.imbue_core.agents.agent_api.data_types import AgentAssistantMessage
from vet.imbue_core.agents.agent_api.data_types import AgentResultMessage
from vet.imbue_core.agents.agent_api.data_types import AgentSystemMessage
from vet.imbue_core.agents.agent_api.data_types import AgentTextBlock
from vet.imbue_core.agents.agent_api.errors import AgentCLINotFoundError
from vet.imbue_core.agents.agent_api.gemini.client import GeminiClient
from vet.imbue_core.agents.agent_api.gemini.data_types import GeminiOptions


class TestFindCli:
    def test_finds_via_which(self) -> None:
        with patch("shutil.which", return_value="/usr/bin/gemini"):
            assert GeminiClient._find_cli() == "/usr/bin/gemini"

    def test_raises_when_not_found(self) -> None:
        with patch("shutil.which", return_value=None):
            with pytest.raises(AgentCLINotFoundError, match="Gemini CLI not found"):
                GeminiClient._find_cli()


class TestBuildCliCmd:
    def test_basic_command(self) -> None:
        options = GeminiOptions(cli_path=Path("/usr/bin/gemini"))
        cmd = GeminiClient._build_cli_cmd(options)
        assert cmd == ["/usr/bin/gemini", "-p", "-", "-o", "stream-json"]

    def test_with_model(self) -> None:
        options = GeminiOptions(cli_path=Path("/usr/bin/gemini"), model="gemini-3-preview")
        cmd = GeminiClient._build_cli_cmd(options)
        assert "--model" in cmd
        assert "gemini-3-preview" in cmd


class TestProcessQuery:
    def test_process_query_yields_messages(self) -> None:
        init_event = {
            "type": "init",
            "timestamp": "2026-04-08T19:41:49.957Z",
            "session_id": "test-session",
            "model": "gemini-3",
        }
        message_event = {
            "type": "message",
            "timestamp": "2026-04-08T19:41:51.917Z",
            "role": "assistant",
            "content": "Hello world",
            "delta": True,
        }
        result_event = {
            "type": "result",
            "timestamp": "2026-04-08T19:41:52.092Z",
            "status": "success",
            "stats": {
                "total_tokens": 100,
                "input_tokens": 50,
                "output_tokens": 50,
            },
        }

        mock_transport = MagicMock()
        mock_transport.receive_messages.return_value = iter([init_event, message_event, result_event])
        mock_transport.write_stdin = MagicMock()
        mock_transport.__enter__ = MagicMock(return_value=mock_transport)
        mock_transport.__exit__ = MagicMock(return_value=False)

        options = GeminiOptions(cli_path=Path("/usr/bin/gemini"))

        with patch(
            "vet.imbue_core.agents.agent_api.gemini.client.AgentSubprocessCLITransport.build",
            return_value=mock_transport,
        ):
            client = GeminiClient(options)
            messages = list(client.process_query("test prompt"))

        assert len(messages) == 3
        assert isinstance(messages[0], AgentSystemMessage)
        assert messages[0].session_id == "test-session"
        assert isinstance(messages[1], AgentAssistantMessage)
        assert messages[1].content[0].text == "Hello world"
        assert isinstance(messages[2], AgentResultMessage)
        assert messages[2].is_error is False

    def test_process_query_error_event(self) -> None:
        error_event = {
            "type": "result",
            "timestamp": "2026-04-08T19:41:52.092Z",
            "status": "error",
            "error": "Something went wrong",
        }

        mock_transport = MagicMock()
        mock_transport.receive_messages.return_value = iter([error_event])
        mock_transport.write_stdin = MagicMock()
        mock_transport.__enter__ = MagicMock(return_value=mock_transport)
        mock_transport.__exit__ = MagicMock(return_value=False)

        options = GeminiOptions(cli_path=Path("/usr/bin/gemini"))

        with patch(
            "vet.imbue_core.agents.agent_api.gemini.client.AgentSubprocessCLITransport.build",
            return_value=mock_transport,
        ):
            client = GeminiClient(options)
            messages = list(client.process_query("test prompt"))

        assert len(messages) == 1
        assert isinstance(messages[0], AgentResultMessage)
        assert messages[0].is_error is True
        assert messages[0].error == "Something went wrong"


class TestBuildContextManager:
    def test_build_yields_client(self) -> None:
        options = GeminiOptions(cli_path=Path("/usr/bin/gemini"))
        with GeminiClient.build(options) as client:
            assert isinstance(client, GeminiClient)
