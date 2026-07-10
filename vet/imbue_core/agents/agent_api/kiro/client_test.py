from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from vet.imbue_core.agents.agent_api.data_types import AgentAssistantMessage
from vet.imbue_core.agents.agent_api.data_types import AgentResultMessage
from vet.imbue_core.agents.agent_api.data_types import AgentSystemMessage
from vet.imbue_core.agents.agent_api.data_types import AgentTextBlock
from vet.imbue_core.agents.agent_api.errors import AgentCLINotFoundError
from vet.imbue_core.agents.agent_api.errors import AgentProcessError
from vet.imbue_core.agents.agent_api.kiro.client import KiroClient
from vet.imbue_core.agents.agent_api.kiro.data_types import KiroOptions

_INIT_RESPONSE = {
    "jsonrpc": "2.0",
    "result": {"protocolVersion": 1, "agentInfo": {"name": "Kiro CLI Agent", "version": "2.11.1"}},
    "id": 0,
}
_SESSION_NEW_RESPONSE = {
    "jsonrpc": "2.0",
    "result": {"sessionId": "sess-1", "modes": {"currentModeId": "kiro_default"}},
    "id": 1,
}


def _make_mock_transport(events: list[dict]) -> MagicMock:
    mock_transport = MagicMock()
    mock_transport.receive_messages.return_value = iter(events)
    mock_transport.send_request = MagicMock()
    mock_transport.__enter__ = MagicMock(return_value=mock_transport)
    mock_transport.__exit__ = MagicMock(return_value=False)
    return mock_transport


class TestFindCli:
    def test_finds_via_which_kiro_cli(self) -> None:
        with patch("shutil.which", side_effect=lambda name: "/usr/bin/kiro-cli" if name == "kiro-cli" else None):
            assert KiroClient._find_cli() == "/usr/bin/kiro-cli"

    def test_finds_via_which_kiro_fallback(self) -> None:
        with patch("shutil.which", side_effect=lambda name: "/usr/bin/kiro" if name == "kiro" else None):
            assert KiroClient._find_cli() == "/usr/bin/kiro"

    def test_finds_via_known_paths(self, tmp_path: Path) -> None:
        fake_home = tmp_path / "home"
        fake_cli = fake_home / ".local/bin/kiro-cli"
        fake_cli.parent.mkdir(parents=True)
        fake_cli.touch()

        with (
            patch("shutil.which", return_value=None),
            patch(
                "vet.imbue_core.agents.agent_api.kiro.client.Path.home",
                return_value=fake_home,
            ),
        ):
            assert KiroClient._find_cli() == str(fake_cli)

    def test_raises_when_not_found(self, tmp_path: Path) -> None:
        with (
            patch("shutil.which", return_value=None),
            patch(
                "vet.imbue_core.agents.agent_api.kiro.client.Path.home",
                return_value=tmp_path / "empty_home",
            ),
        ):
            with pytest.raises(AgentCLINotFoundError, match="Kiro CLI not found"):
                KiroClient._find_cli()


class TestBuildCliCmd:
    def test_basic_command(self) -> None:
        options = KiroOptions(cli_path=Path("/usr/bin/kiro-cli"))
        cmd = KiroClient._build_cli_cmd(options)
        assert cmd == ["/usr/bin/kiro-cli", "acp", "--trust-all-tools", "--agent", "kiro_default"]

    def test_with_model(self) -> None:
        options = KiroOptions(cli_path=Path("/usr/bin/kiro-cli"), model="claude-haiku-4.5")
        cmd = KiroClient._build_cli_cmd(options)
        assert "--model" in cmd
        assert "claude-haiku-4.5" in cmd

    def test_agent_none_omits_flag(self) -> None:
        options = KiroOptions(cli_path=Path("/usr/bin/kiro-cli"), agent=None)
        cmd = KiroClient._build_cli_cmd(options)
        assert "--agent" not in cmd

    def test_cached_placeholder(self) -> None:
        options = KiroOptions(is_cached=True)
        cmd = KiroClient._build_cli_cmd(options)
        assert cmd == ["CACHED_KIRO_EXEC_PLACEHOLDER"]


class TestProcessQuery:
    def test_process_query_yields_normalized_messages(self) -> None:
        prompt_end_response = {"jsonrpc": "2.0", "result": {"stopReason": "end_turn"}, "id": 2}
        chunk_1 = {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "sess-1",
                "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "p"}},
            },
        }
        chunk_2 = {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "sess-1",
                "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "ong"}},
            },
        }
        noise = {"jsonrpc": "2.0", "method": "_kiro.dev/metadata", "params": {"sessionId": "sess-1"}}

        events = [_INIT_RESPONSE, _SESSION_NEW_RESPONSE, noise, chunk_1, chunk_2, prompt_end_response]
        mock_transport = _make_mock_transport(events)

        options = KiroOptions(cli_path=Path("/usr/bin/kiro-cli"))
        with patch(
            "vet.imbue_core.agents.agent_api.kiro.client.AgentSubprocessCLITransport.build",
            return_value=mock_transport,
        ):
            client = KiroClient(options, mock_transport)
            messages = list(client.process_query("Reply with exactly the word: pong"))

        assert isinstance(messages[0], AgentSystemMessage)
        assert messages[0].session_id == "sess-1"

        assert isinstance(messages[1], AgentAssistantMessage)
        assert isinstance(messages[1].content[0], AgentTextBlock)
        assert messages[1].content[0].text == "p"

        assert isinstance(messages[2], AgentAssistantMessage)
        assert messages[2].content[0].text == "ong"

        result = messages[-1]
        assert isinstance(result, AgentResultMessage)
        assert result.is_error is False
        assert result.result == "pong"
        assert result.session_id == "sess-1"

    def test_non_end_turn_stop_reason_marks_error(self) -> None:
        prompt_end_response = {"jsonrpc": "2.0", "result": {"stopReason": "refusal"}, "id": 2}
        events = [_INIT_RESPONSE, _SESSION_NEW_RESPONSE, prompt_end_response]
        mock_transport = _make_mock_transport(events)

        options = KiroOptions(cli_path=Path("/usr/bin/kiro-cli"))
        with patch(
            "vet.imbue_core.agents.agent_api.kiro.client.AgentSubprocessCLITransport.build",
            return_value=mock_transport,
        ):
            client = KiroClient(options, mock_transport)
            messages = list(client.process_query("test prompt"))

        result = messages[-1]
        assert isinstance(result, AgentResultMessage)
        assert result.is_error is True
        assert result.error == "refusal"

    def test_handshake_error_raises_agent_process_error(self) -> None:
        error_response = {"jsonrpc": "2.0", "error": {"code": -32000, "message": "not authenticated"}, "id": 1}
        events = [_INIT_RESPONSE, error_response]
        mock_transport = _make_mock_transport(events)

        options = KiroOptions(cli_path=Path("/usr/bin/kiro-cli"))
        with patch(
            "vet.imbue_core.agents.agent_api.kiro.client.AgentSubprocessCLITransport.build",
            return_value=mock_transport,
        ):
            client = KiroClient(options, mock_transport)
            with pytest.raises(AgentProcessError, match="not authenticated"):
                list(client.process_query("test prompt"))

    def test_stream_closes_before_session_new_response_raises_agent_process_error(self) -> None:
        # The CLI exits (or closes stdout) after initialize but before ever responding
        # to session/new -- the stream ends without a matching id.
        events = [_INIT_RESPONSE]
        mock_transport = _make_mock_transport(events)

        options = KiroOptions(cli_path=Path("/usr/bin/kiro-cli"))
        with patch(
            "vet.imbue_core.agents.agent_api.kiro.client.AgentSubprocessCLITransport.build",
            return_value=mock_transport,
        ):
            client = KiroClient(options, mock_transport)
            with pytest.raises(AgentProcessError, match="closed the stream"):
                list(client.process_query("test prompt"))


class TestBuildContextManager:
    def test_build_yields_client(self) -> None:
        options = KiroOptions(cli_path=Path("/usr/bin/kiro-cli"))
        mock_transport = _make_mock_transport([_INIT_RESPONSE])

        with patch(
            "vet.imbue_core.agents.agent_api.kiro.client.AgentSubprocessCLITransport.build",
            return_value=mock_transport,
        ):
            with KiroClient.build(options) as client:
                assert isinstance(client, KiroClient)
