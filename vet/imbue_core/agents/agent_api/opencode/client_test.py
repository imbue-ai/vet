import json
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from vet.imbue_core.agents.agent_api.data_types import AgentAssistantMessage
from vet.imbue_core.agents.agent_api.data_types import AgentResultMessage
from vet.imbue_core.agents.agent_api.data_types import AgentTextBlock
from vet.imbue_core.agents.agent_api.errors import AgentCLINotFoundError
from vet.imbue_core.agents.agent_api.opencode.client import OpenCodeClient
from vet.imbue_core.agents.agent_api.opencode.data_types import OpenCodeOptions


class TestFindCli:
    def test_finds_via_which(self) -> None:
        with patch("shutil.which", return_value="/usr/bin/opencode"):
            assert OpenCodeClient._find_cli() == "/usr/bin/opencode"

    def test_finds_via_known_paths(self, tmp_path: Path) -> None:
        fake_home = tmp_path / "home"
        fake_cli = fake_home / ".local/bin/opencode"
        fake_cli.parent.mkdir(parents=True)
        fake_cli.touch()

        with (
            patch("shutil.which", return_value=None),
            patch(
                "vet.imbue_core.agents.agent_api.opencode.client.Path.home",
                return_value=fake_home,
            ),
        ):
            assert OpenCodeClient._find_cli() == str(fake_cli)

    def test_raises_when_not_found_no_node(self) -> None:
        with patch("shutil.which", return_value=None):
            with pytest.raises(AgentCLINotFoundError, match="Node.js is required"):
                OpenCodeClient._find_cli()

    def test_raises_when_not_found_with_node(self) -> None:
        def which_side_effect(name: str) -> str | None:
            if name == "node":
                return "/usr/bin/node"
            return None

        with patch("shutil.which", side_effect=which_side_effect):
            with pytest.raises(AgentCLINotFoundError, match="Ensure it is installed"):
                OpenCodeClient._find_cli()


class TestBuildCliCmd:
    def test_basic_command(self) -> None:
        options = OpenCodeOptions(cli_path=Path("/usr/bin/opencode"))
        cmd = OpenCodeClient._build_cli_cmd(options)
        assert cmd == ["/usr/bin/opencode", "run", "--format", "json"]

    def test_with_model(self) -> None:
        options = OpenCodeOptions(cli_path=Path("/usr/bin/opencode"), model="anthropic/claude-opus-4-6")
        cmd = OpenCodeClient._build_cli_cmd(options)
        assert "--model" in cmd
        assert "anthropic/claude-opus-4-6" in cmd

    def test_with_cwd(self) -> None:
        options = OpenCodeOptions(cli_path=Path("/usr/bin/opencode"), cwd="/my/project")
        cmd = OpenCodeClient._build_cli_cmd(options)
        assert "--dir" in cmd
        assert "/my/project" in cmd

    def test_cached_placeholder(self) -> None:
        options = OpenCodeOptions(is_cached=True)
        cmd = OpenCodeClient._build_cli_cmd(options)
        assert cmd == ["CACHED_OPENCODE_EXEC_PLACEHOLDER"]


class TestProcessQuery:
    def test_process_query_yields_messages(self) -> None:
        text_event = {
            "type": "text",
            "timestamp": 1,
            "sessionID": "ses_test",
            "part": {
                "id": "prt_1",
                "sessionID": "ses_test",
                "messageID": "msg_1",
                "type": "text",
                "text": "Hello world",
            },
        }
        result_event = {
            "type": "step_finish",
            "timestamp": 2,
            "sessionID": "ses_test",
            "part": {
                "id": "prt_2",
                "sessionID": "ses_test",
                "messageID": "msg_1",
                "type": "step-finish",
                "reason": "stop",
                "cost": 0.01,
                "tokens": {
                    "total": 100,
                    "input": 50,
                    "output": 50,
                    "reasoning": 0,
                    "cache": {"read": 0, "write": 0},
                },
            },
        }

        mock_transport = MagicMock()
        mock_transport.receive_messages.return_value = iter([text_event, result_event])
        mock_transport.write_stdin = MagicMock()
        mock_transport.__enter__ = MagicMock(return_value=mock_transport)
        mock_transport.__exit__ = MagicMock(return_value=False)

        options = OpenCodeOptions(cli_path=Path("/usr/bin/opencode"))

        with patch(
            "vet.imbue_core.agents.agent_api.opencode.client.AgentSubprocessCLITransport.build",
            return_value=mock_transport,
        ):
            client = OpenCodeClient(options)
            messages = list(client.process_query("test prompt"))

        assert len(messages) == 2
        assert isinstance(messages[0], AgentAssistantMessage)
        assert isinstance(messages[0].content[0], AgentTextBlock)
        assert messages[0].content[0].text == "Hello world"
        assert isinstance(messages[1], AgentResultMessage)
        assert messages[1].is_error is False

    def test_process_query_error_event(self) -> None:
        error_event = {
            "type": "error",
            "timestamp": 1,
            "sessionID": "ses_test",
            "part": {
                "message": "Rate limit exceeded",
            },
        }

        mock_transport = MagicMock()
        mock_transport.receive_messages.return_value = iter([error_event])
        mock_transport.write_stdin = MagicMock()
        mock_transport.__enter__ = MagicMock(return_value=mock_transport)
        mock_transport.__exit__ = MagicMock(return_value=False)

        options = OpenCodeOptions(cli_path=Path("/usr/bin/opencode"))

        with patch(
            "vet.imbue_core.agents.agent_api.opencode.client.AgentSubprocessCLITransport.build",
            return_value=mock_transport,
        ):
            client = OpenCodeClient(options)
            messages = list(client.process_query("test prompt"))

        assert len(messages) == 1
        assert isinstance(messages[0], AgentResultMessage)
        assert messages[0].is_error is True
        assert messages[0].error == "Rate limit exceeded"


class TestTransportOptions:
    def test_transport_not_passed_cwd(self) -> None:
        text_event = {
            "type": "text",
            "timestamp": 1,
            "sessionID": "ses_test",
            "part": {
                "id": "prt_1",
                "sessionID": "ses_test",
                "messageID": "msg_1",
                "type": "text",
                "text": "hi",
            },
        }
        result_event = {
            "type": "step_finish",
            "timestamp": 2,
            "sessionID": "ses_test",
            "part": {
                "id": "prt_2",
                "sessionID": "ses_test",
                "messageID": "msg_1",
                "type": "step-finish",
                "reason": "stop",
            },
        }

        mock_transport = MagicMock()
        mock_transport.receive_messages.return_value = iter([text_event, result_event])
        mock_transport.write_stdin = MagicMock()
        mock_transport.__enter__ = MagicMock(return_value=mock_transport)
        mock_transport.__exit__ = MagicMock(return_value=False)

        options = OpenCodeOptions(cli_path=Path("/usr/bin/opencode"), cwd="/my/project")

        with patch(
            "vet.imbue_core.agents.agent_api.opencode.client.AgentSubprocessCLITransport.build",
            return_value=mock_transport,
        ) as mock_build:
            client = OpenCodeClient(options)
            list(client.process_query("test"))

        transport_options = mock_build.call_args[0][0]
        assert transport_options.cwd is None


class TestBuildContextManager:
    def test_build_yields_client(self) -> None:
        options = OpenCodeOptions(cli_path=Path("/usr/bin/opencode"))
        with OpenCodeClient.build(options) as client:
            assert isinstance(client, OpenCodeClient)
