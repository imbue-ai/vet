"""Tests for vet-history CLI."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from vet_history.cli import main, create_parser


class TestCLIParser:
    """Tests for CLI argument parsing."""

    def test_parser_creation(self) -> None:
        """Test that parser is created successfully."""
        parser = create_parser()
        assert parser is not None
        assert parser.prog == "vet-history"

    def test_version_flag(self) -> None:
        """Test --version flag."""
        parser = create_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--version"])
        assert exc_info.value.code == 0

    def test_help_flag(self) -> None:
        """Test --help flag."""
        parser = create_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--help"])
        assert exc_info.value.code == 0

    def test_claude_code_subcommand(self) -> None:
        """Test claude-code subcommand parsing."""
        parser = create_parser()

        # Default (--latest)
        args = parser.parse_args(["claude-code"])
        assert args.agent == "claude-code"
        assert args.latest is True

        # With --session
        args = parser.parse_args(["claude-code", "--session", "abc123"])
        assert args.session == "abc123"

        # With --project
        args = parser.parse_args(["claude-code", "--project", "/some/path"])
        assert args.project == Path("/some/path")

        # With --list
        args = parser.parse_args(["claude-code", "--list"])
        assert args.list is True

    def test_opencode_subcommand(self) -> None:
        """Test opencode subcommand parsing."""
        parser = create_parser()

        # Default (--latest)
        args = parser.parse_args(["opencode"])
        assert args.agent == "opencode"
        assert args.latest is True

        # With --session
        args = parser.parse_args(["opencode", "--session", "ses_abc123"])
        assert args.session == "ses_abc123"

        # With --project
        args = parser.parse_args(["opencode", "--project", "."])
        assert args.project == Path(".")

        # With --list
        args = parser.parse_args(["opencode", "--list"])
        assert args.list is True

    def test_codex_subcommand(self) -> None:
        """Test codex subcommand parsing."""
        parser = create_parser()

        # Default (--latest)
        args = parser.parse_args(["codex"])
        assert args.agent == "codex"
        assert args.latest is True

        # With --session
        args = parser.parse_args(["codex", "--session", "uuid-123"])
        assert args.session == "uuid-123"

        # With --list
        args = parser.parse_args(["codex", "--list"])
        assert args.list is True

    def test_missing_subcommand(self) -> None:
        """Test that missing subcommand raises error."""
        parser = create_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args([])
        assert exc_info.value.code != 0


class TestCLIClaudeCode:
    """Tests for claude-code CLI commands."""

    def test_list_sessions(self, claude_code_session_dir: Path, capsys) -> None:
        """Test listing Claude Code sessions."""
        with mock.patch(
            "vet_history.loaders.claude_code.get_claude_code_projects_path",
            return_value=claude_code_session_dir,
        ):
            exit_code = main(["claude-code", "--list"])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Available Claude Code sessions" in captured.out
        assert "test-session-123" in captured.out

    def test_load_latest(self, claude_code_session_dir: Path, capsys) -> None:
        """Test loading latest Claude Code session."""
        with mock.patch(
            "vet_history.loaders.claude_code.get_claude_code_projects_path",
            return_value=claude_code_session_dir,
        ):
            exit_code = main(["claude-code", "--latest"])

        assert exit_code == 0
        captured = capsys.readouterr()
        # Output should be JSONL
        lines = captured.out.strip().split("\n")
        assert len(lines) >= 1
        # Verify each line is valid JSON
        for line in lines:
            data = json.loads(line)
            assert "object_type" in data

    def test_load_by_session_id(self, claude_code_session_dir: Path, capsys) -> None:
        """Test loading Claude Code session by ID."""
        with mock.patch(
            "vet_history.loaders.claude_code.get_claude_code_projects_path",
            return_value=claude_code_session_dir,
        ):
            exit_code = main(["claude-code", "--session", "test-session-123"])

        assert exit_code == 0
        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert len(lines) >= 1

    def test_session_not_found(self, claude_code_session_dir: Path, capsys) -> None:
        """Test error when session not found."""
        with mock.patch(
            "vet_history.loaders.claude_code.get_claude_code_projects_path",
            return_value=claude_code_session_dir,
        ):
            exit_code = main(["claude-code", "--session", "nonexistent"])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Error" in captured.err

    def test_no_sessions_found(self, temp_dir: Path, capsys) -> None:
        """Test error when no sessions found."""
        empty_projects = temp_dir / "projects"
        empty_projects.mkdir()

        with mock.patch(
            "vet_history.loaders.claude_code.get_claude_code_projects_path",
            return_value=empty_projects,
        ):
            exit_code = main(["claude-code", "--list"])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "No sessions found" in captured.err


class TestCLIOpenCode:
    """Tests for opencode CLI commands."""

    def test_list_sessions(self, opencode_storage_dir: Path, capsys) -> None:
        """Test listing OpenCode sessions."""
        with mock.patch(
            "vet_history.loaders.opencode.get_opencode_storage_path",
            return_value=opencode_storage_dir,
        ):
            exit_code = main(["opencode", "--list"])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Available OpenCode sessions" in captured.out
        assert "ses_test123" in captured.out

    def test_load_latest(self, opencode_storage_dir: Path, capsys) -> None:
        """Test loading latest OpenCode session."""
        with mock.patch(
            "vet_history.loaders.opencode.get_opencode_storage_path",
            return_value=opencode_storage_dir,
        ):
            exit_code = main(["opencode", "--latest"])

        assert exit_code == 0
        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert len(lines) >= 1
        for line in lines:
            data = json.loads(line)
            assert "object_type" in data

    def test_load_by_session_id(self, opencode_storage_dir: Path, capsys) -> None:
        """Test loading OpenCode session by ID."""
        with mock.patch(
            "vet_history.loaders.opencode.get_opencode_storage_path",
            return_value=opencode_storage_dir,
        ):
            exit_code = main(["opencode", "--session", "ses_test123"])

        assert exit_code == 0
        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert len(lines) >= 1

    def test_session_not_found(self, opencode_storage_dir: Path, capsys) -> None:
        """Test error when session not found."""
        with mock.patch(
            "vet_history.loaders.opencode.get_opencode_storage_path",
            return_value=opencode_storage_dir,
        ):
            exit_code = main(["opencode", "--session", "nonexistent"])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Error" in captured.err


class TestCLICodex:
    """Tests for codex CLI commands."""

    def test_list_sessions(self, codex_session_dir: Path, capsys) -> None:
        """Test listing Codex sessions."""
        sessions_dir = codex_session_dir / "sessions"
        with mock.patch(
            "vet_history.loaders.codex.get_codex_sessions_path",
            return_value=sessions_dir,
        ):
            exit_code = main(["codex", "--list"])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Available Codex CLI sessions" in captured.out
        assert "codex-session-123" in captured.out

    def test_load_latest(self, codex_session_dir: Path, capsys) -> None:
        """Test loading latest Codex session."""
        sessions_dir = codex_session_dir / "sessions"
        with mock.patch(
            "vet_history.loaders.codex.get_codex_sessions_path",
            return_value=sessions_dir,
        ):
            exit_code = main(["codex", "--latest"])

        assert exit_code == 0
        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert len(lines) >= 1
        for line in lines:
            data = json.loads(line)
            assert "object_type" in data

    def test_load_by_session_id(self, codex_session_dir: Path, capsys) -> None:
        """Test loading Codex session by ID."""
        sessions_dir = codex_session_dir / "sessions"
        with mock.patch(
            "vet_history.loaders.codex.get_codex_sessions_path",
            return_value=sessions_dir,
        ):
            exit_code = main(["codex", "--session", "codex-session-123"])

        assert exit_code == 0
        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert len(lines) >= 1

    def test_session_not_found(self, codex_session_dir: Path, capsys) -> None:
        """Test error when session not found."""
        sessions_dir = codex_session_dir / "sessions"
        with mock.patch(
            "vet_history.loaders.codex.get_codex_sessions_path",
            return_value=sessions_dir,
        ):
            exit_code = main(["codex", "--session", "nonexistent"])

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Error" in captured.err


class TestCLIOutputFormat:
    """Tests for CLI output format."""

    def test_jsonl_output_format(self, claude_code_session_dir: Path, capsys) -> None:
        """Test that output is valid JSONL format."""
        with mock.patch(
            "vet_history.loaders.claude_code.get_claude_code_projects_path",
            return_value=claude_code_session_dir,
        ):
            exit_code = main(["claude-code", "--latest"])

        assert exit_code == 0
        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")

        for line in lines:
            # Each line should be valid JSON
            data = json.loads(line)

            # Should have object_type field
            assert "object_type" in data

            # Should be one of the expected message types
            assert data["object_type"] in [
                "ChatInputUserMessage",
                "ResponseBlockAgentMessage",
            ]

    def test_user_message_fields(self, claude_code_session_dir: Path, capsys) -> None:
        """Test that user messages have required fields."""
        with mock.patch(
            "vet_history.loaders.claude_code.get_claude_code_projects_path",
            return_value=claude_code_session_dir,
        ):
            exit_code = main(["claude-code", "--latest"])

        assert exit_code == 0
        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")

        user_msgs = [json.loads(line) for line in lines if json.loads(line)["object_type"] == "ChatInputUserMessage"]

        assert len(user_msgs) >= 1
        for msg in user_msgs:
            assert "text" in msg
            assert "source" in msg
            assert msg["source"] == "USER"

    def test_agent_message_fields(self, claude_code_session_dir: Path, capsys) -> None:
        """Test that agent messages have required fields."""
        with mock.patch(
            "vet_history.loaders.claude_code.get_claude_code_projects_path",
            return_value=claude_code_session_dir,
        ):
            exit_code = main(["claude-code", "--latest"])

        assert exit_code == 0
        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")

        agent_msgs = [
            json.loads(line) for line in lines if json.loads(line)["object_type"] == "ResponseBlockAgentMessage"
        ]

        assert len(agent_msgs) >= 1
        for msg in agent_msgs:
            assert "role" in msg
            assert "content" in msg
            assert "source" in msg
            assert msg["source"] == "AGENT"


class TestCLIExitCodes:
    """Tests for CLI exit codes."""

    def test_success_exit_code(self, claude_code_session_dir: Path) -> None:
        """Test exit code 0 on success."""
        with mock.patch(
            "vet_history.loaders.claude_code.get_claude_code_projects_path",
            return_value=claude_code_session_dir,
        ):
            exit_code = main(["claude-code", "--latest"])

        assert exit_code == 0

    def test_error_exit_code(self, temp_dir: Path) -> None:
        """Test exit code 1 on error."""
        nonexistent = temp_dir / "nonexistent"

        with mock.patch(
            "vet_history.loaders.claude_code.get_claude_code_projects_path",
            return_value=nonexistent,
        ):
            exit_code = main(["claude-code", "--latest"])

        assert exit_code == 1
