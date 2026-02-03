"""Tests for Claude Code conversation history loader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vet_history.loaders.claude_code import ClaudeCodeLoader
from vet_history.loaders.base import (
    SessionNotFoundError,
    SessionParseError,
    LoaderError,
)
from vet_history.types import (
    ChatInputUserMessage,
    ResponseBlockAgentMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
)


class TestClaudeCodeLoader:
    """Tests for ClaudeCodeLoader class."""

    def test_init_with_valid_path(self, claude_code_session_dir: Path) -> None:
        """Test loader initialization with valid history path."""
        loader = ClaudeCodeLoader(history_path=claude_code_session_dir)
        assert loader.history_path == claude_code_session_dir
        assert loader.AGENT_NAME == "claude-code"

    def test_init_with_nonexistent_path(self, temp_dir: Path) -> None:
        """Test loader initialization with nonexistent path raises error."""
        nonexistent = temp_dir / "nonexistent"
        with pytest.raises(LoaderError):
            ClaudeCodeLoader(history_path=nonexistent)

    def test_list_sessions(self, claude_code_session_dir: Path) -> None:
        """Test listing available sessions."""
        loader = ClaudeCodeLoader(history_path=claude_code_session_dir)
        sessions = loader.list_sessions()

        assert len(sessions) == 1
        session = sessions[0]
        assert session.session_id == "test-session-123"
        assert session.agent == "claude-code"
        assert session.project_path is not None
        assert "home" in session.project_path and "user" in session.project_path

    def test_list_sessions_with_project_filter(self, claude_code_session_dir: Path) -> None:
        """Test listing sessions filtered by project path."""
        loader = ClaudeCodeLoader(history_path=claude_code_session_dir)

        # Should find session for matching project
        sessions = loader.list_sessions(project_path=Path("/home/user/project"))
        assert len(sessions) == 1

        # Should not find session for different project
        sessions = loader.list_sessions(project_path=Path("/home/other/project"))
        assert len(sessions) == 0

    def test_list_sessions_empty_directory(self, temp_dir: Path) -> None:
        """Test listing sessions when no sessions exist."""
        projects_dir = temp_dir / "projects"
        projects_dir.mkdir()

        loader = ClaudeCodeLoader(history_path=projects_dir)
        sessions = loader.list_sessions()
        assert len(sessions) == 0

    def test_get_latest_session(self, claude_code_session_dir: Path) -> None:
        """Test getting the most recent session."""
        loader = ClaudeCodeLoader(history_path=claude_code_session_dir)
        session = loader.get_latest_session()

        assert session.session_id == "test-session-123"
        assert session.agent == "claude-code"

    def test_get_latest_session_not_found(self, temp_dir: Path) -> None:
        """Test getting latest session when none exist raises error."""
        projects_dir = temp_dir / "projects"
        projects_dir.mkdir()

        loader = ClaudeCodeLoader(history_path=projects_dir)
        with pytest.raises(SessionNotFoundError):
            loader.get_latest_session()

    def test_get_session_by_id(self, claude_code_session_dir: Path) -> None:
        """Test getting a specific session by ID."""
        loader = ClaudeCodeLoader(history_path=claude_code_session_dir)
        session = loader.get_session_by_id("test-session-123")

        assert session.session_id == "test-session-123"
        assert session.agent == "claude-code"

    def test_get_session_by_id_not_found(self, claude_code_session_dir: Path) -> None:
        """Test getting nonexistent session by ID raises error."""
        loader = ClaudeCodeLoader(history_path=claude_code_session_dir)
        with pytest.raises(SessionNotFoundError):
            loader.get_session_by_id("nonexistent-session")

    def test_load_session(self, claude_code_session_dir: Path) -> None:
        """Test loading a session's conversation history."""
        loader = ClaudeCodeLoader(history_path=claude_code_session_dir)
        session = loader.get_session_by_id("test-session-123")
        messages = loader.load_session(session)

        assert len(messages) >= 2  # At least user message and assistant message

        # Check first message is user message
        user_msg = messages[0]
        assert isinstance(user_msg, ChatInputUserMessage)
        assert "fix the bug" in user_msg.text.lower()

        # Check second message is assistant response
        assistant_msg = messages[1]
        assert isinstance(assistant_msg, ResponseBlockAgentMessage)
        assert assistant_msg.role == "assistant"
        assert len(assistant_msg.content) > 0

    def test_load_session_with_tool_use(self, claude_code_session_dir: Path) -> None:
        """Test loading a session with tool use blocks."""
        loader = ClaudeCodeLoader(history_path=claude_code_session_dir)
        messages = loader.load_latest()

        # Find tool use message
        tool_use_msgs = [
            m
            for m in messages
            if isinstance(m, ResponseBlockAgentMessage) and any(isinstance(b, ToolUseBlock) for b in m.content)
        ]
        assert len(tool_use_msgs) >= 1

        tool_use_msg = tool_use_msgs[0]
        tool_block = next(b for b in tool_use_msg.content if isinstance(b, ToolUseBlock))
        assert tool_block.name == "Read"
        assert "filePath" in tool_block.input

    def test_load_session_with_tool_result(self, claude_code_session_dir: Path) -> None:
        """Test loading a session with tool result blocks."""
        loader = ClaudeCodeLoader(history_path=claude_code_session_dir)
        messages = loader.load_latest()

        # Find tool result message
        tool_result_msgs = [
            m
            for m in messages
            if isinstance(m, ResponseBlockAgentMessage) and any(isinstance(b, ToolResultBlock) for b in m.content)
        ]
        assert len(tool_result_msgs) >= 1

        tool_result_msg = tool_result_msgs[0]
        result_block = next(b for b in tool_result_msg.content if isinstance(b, ToolResultBlock))
        assert result_block.tool_use_id == "toolu_001"
        assert not result_block.is_error

    def test_load_by_id(self, claude_code_session_dir: Path) -> None:
        """Test load_by_id convenience method."""
        loader = ClaudeCodeLoader(history_path=claude_code_session_dir)
        messages = loader.load_by_id("test-session-123")

        assert len(messages) >= 2
        assert isinstance(messages[0], ChatInputUserMessage)

    def test_load_latest(self, claude_code_session_dir: Path) -> None:
        """Test load_latest convenience method."""
        loader = ClaudeCodeLoader(history_path=claude_code_session_dir)
        messages = loader.load_latest()

        assert len(messages) >= 2
        assert isinstance(messages[0], ChatInputUserMessage)


class TestClaudeCodeMessageConversion:
    """Tests for Claude Code message conversion."""

    def test_convert_user_message(self, claude_code_session_dir: Path, claude_code_user_message: dict) -> None:
        """Test converting a user message."""
        loader = ClaudeCodeLoader(history_path=claude_code_session_dir)
        result = loader._convert_message(claude_code_user_message)

        assert result is not None
        assert isinstance(result, ChatInputUserMessage)
        assert "fix the bug" in result.text.lower()
        assert result.message_id == "user-msg-001"

    def test_convert_assistant_message(
        self, claude_code_session_dir: Path, claude_code_assistant_message: dict
    ) -> None:
        """Test converting an assistant message."""
        loader = ClaudeCodeLoader(history_path=claude_code_session_dir)
        result = loader._convert_message(claude_code_assistant_message)

        assert result is not None
        assert isinstance(result, ResponseBlockAgentMessage)
        assert result.role == "assistant"
        assert len(result.content) == 1
        assert isinstance(result.content[0], TextBlock)
        assert "fix the bug" in result.content[0].text.lower()

    def test_convert_tool_use_message(self, claude_code_session_dir: Path, claude_code_tool_use_message: dict) -> None:
        """Test converting a tool use message."""
        loader = ClaudeCodeLoader(history_path=claude_code_session_dir)
        result = loader._convert_message(claude_code_tool_use_message)

        assert result is not None
        assert isinstance(result, ResponseBlockAgentMessage)
        assert len(result.content) == 1
        assert isinstance(result.content[0], ToolUseBlock)
        assert result.content[0].name == "Read"

    def test_convert_queue_operation_skipped(self, claude_code_session_dir: Path) -> None:
        """Test that queue operation messages are skipped."""
        loader = ClaudeCodeLoader(history_path=claude_code_session_dir)
        queue_op = {
            "type": "queue-operation",
            "operation": "dequeue",
            "timestamp": "2026-01-30T20:27:17.058Z",
            "sessionId": "test-session-123",
        }
        result = loader._convert_message(queue_op)
        assert result is None

    def test_convert_empty_content_skipped(self, claude_code_session_dir: Path) -> None:
        """Test that messages with empty content are skipped."""
        loader = ClaudeCodeLoader(history_path=claude_code_session_dir)
        empty_msg = {
            "type": "user",
            "uuid": "empty-001",
            "timestamp": "2026-01-30T20:27:17.000Z",
            "message": {"role": "user", "content": []},
        }
        result = loader._convert_message(empty_msg)
        assert result is None


class TestClaudeCodeMultipleSessions:
    """Tests for handling multiple sessions."""

    def test_multiple_sessions_sorted_by_time(self, temp_dir: Path) -> None:
        """Test that sessions are sorted by modification time."""
        projects_dir = temp_dir / "projects"
        project_dir = projects_dir / "-home-user-project"
        project_dir.mkdir(parents=True)

        # Create older session
        older_session = project_dir / "session-older.jsonl"
        with open(older_session, "w") as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "msg-1",
                        "timestamp": "2026-01-01T10:00:00.000Z",
                        "message": {
                            "role": "user",
                            "content": [{"type": "text", "text": "older"}],
                        },
                    }
                )
                + "\n"
            )

        # Create newer session (touch to make it newer)
        newer_session = project_dir / "session-newer.jsonl"
        with open(newer_session, "w") as f:
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "msg-2",
                        "timestamp": "2026-01-02T10:00:00.000Z",
                        "message": {
                            "role": "user",
                            "content": [{"type": "text", "text": "newer"}],
                        },
                    }
                )
                + "\n"
            )

        import time

        time.sleep(0.01)  # Ensure different mtime
        newer_session.touch()

        loader = ClaudeCodeLoader(history_path=projects_dir)
        sessions = loader.list_sessions()

        assert len(sessions) == 2
        assert sessions[0].session_id == "session-newer"  # Newest first
        assert sessions[1].session_id == "session-older"


class TestClaudeCodeEdgeCases:
    """Tests for edge cases and error handling."""

    def test_malformed_json_line_skipped(self, temp_dir: Path) -> None:
        """Test that malformed JSON lines are skipped gracefully."""
        projects_dir = temp_dir / "projects"
        project_dir = projects_dir / "-home-user-project"
        project_dir.mkdir(parents=True)

        session_file = project_dir / "test-session.jsonl"
        with open(session_file, "w") as f:
            f.write("not valid json\n")
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "msg-1",
                        "timestamp": "2026-01-01T10:00:00.000Z",
                        "message": {
                            "role": "user",
                            "content": [{"type": "text", "text": "valid"}],
                        },
                    }
                )
                + "\n"
            )

        loader = ClaudeCodeLoader(history_path=projects_dir)
        messages = loader.load_latest()

        # Should have loaded the valid message, skipped the malformed one
        assert len(messages) == 1
        assert isinstance(messages[0], ChatInputUserMessage)
        assert messages[0].text == "valid"

    def test_empty_session_file(self, temp_dir: Path) -> None:
        """Test handling of empty session files."""
        projects_dir = temp_dir / "projects"
        project_dir = projects_dir / "-home-user-project"
        project_dir.mkdir(parents=True)

        session_file = project_dir / "empty-session.jsonl"
        session_file.touch()

        loader = ClaudeCodeLoader(history_path=projects_dir)
        messages = loader.load_latest()

        assert len(messages) == 0

    def test_timestamp_parsing(self, claude_code_session_dir: Path) -> None:
        """Test that timestamps are correctly parsed."""
        loader = ClaudeCodeLoader(history_path=claude_code_session_dir)
        messages = loader.load_latest()

        for msg in messages:
            assert msg.approximate_creation_time is not None
            # Check it's a valid datetime
            assert msg.approximate_creation_time.year >= 2024
