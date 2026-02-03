"""Tests for OpenCode conversation history loader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vet_history.loaders.opencode import OpenCodeLoader
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


class TestOpenCodeLoader:
    """Tests for OpenCodeLoader class."""

    def test_init_with_valid_path(self, opencode_storage_dir: Path) -> None:
        """Test loader initialization with valid storage path."""
        loader = OpenCodeLoader(history_path=opencode_storage_dir)
        assert loader.history_path == opencode_storage_dir
        assert loader.AGENT_NAME == "opencode"

    def test_init_with_nonexistent_path(self, temp_dir: Path) -> None:
        """Test loader initialization with nonexistent path raises error."""
        nonexistent = temp_dir / "nonexistent"
        with pytest.raises(LoaderError):
            OpenCodeLoader(history_path=nonexistent)

    def test_list_sessions(self, opencode_storage_dir: Path) -> None:
        """Test listing available sessions."""
        loader = OpenCodeLoader(history_path=opencode_storage_dir)
        sessions = loader.list_sessions()

        assert len(sessions) == 1
        session = sessions[0]
        assert session.session_id == "ses_test123"
        assert session.agent == "opencode"
        assert session.title == "Fix login bug"
        assert session.project_path == "/home/user/project"

    def test_list_sessions_with_project_filter(self, opencode_storage_dir: Path) -> None:
        """Test listing sessions filtered by project path."""
        loader = OpenCodeLoader(history_path=opencode_storage_dir)

        # Should find session for matching project
        sessions = loader.list_sessions(project_path=Path("/home/user/project"))
        assert len(sessions) == 1

        # Should not find session for different project
        sessions = loader.list_sessions(project_path=Path("/home/other/project"))
        assert len(sessions) == 0

    def test_list_sessions_empty_storage(self, temp_dir: Path) -> None:
        """Test listing sessions when no sessions exist."""
        storage_dir = temp_dir / "storage"
        session_dir = storage_dir / "session"
        session_dir.mkdir(parents=True)

        loader = OpenCodeLoader(history_path=storage_dir)
        sessions = loader.list_sessions()
        assert len(sessions) == 0

    def test_get_latest_session(self, opencode_storage_dir: Path) -> None:
        """Test getting the most recent session."""
        loader = OpenCodeLoader(history_path=opencode_storage_dir)
        session = loader.get_latest_session()

        assert session.session_id == "ses_test123"
        assert session.agent == "opencode"

    def test_get_latest_session_not_found(self, temp_dir: Path) -> None:
        """Test getting latest session when none exist raises error."""
        storage_dir = temp_dir / "storage"
        session_dir = storage_dir / "session"
        session_dir.mkdir(parents=True)

        loader = OpenCodeLoader(history_path=storage_dir)
        with pytest.raises(SessionNotFoundError):
            loader.get_latest_session()

    def test_get_session_by_id(self, opencode_storage_dir: Path) -> None:
        """Test getting a specific session by ID."""
        loader = OpenCodeLoader(history_path=opencode_storage_dir)
        session = loader.get_session_by_id("ses_test123")

        assert session.session_id == "ses_test123"
        assert session.agent == "opencode"
        assert session.title == "Fix login bug"

    def test_get_session_by_id_not_found(self, opencode_storage_dir: Path) -> None:
        """Test getting nonexistent session by ID raises error."""
        loader = OpenCodeLoader(history_path=opencode_storage_dir)
        with pytest.raises(SessionNotFoundError):
            loader.get_session_by_id("nonexistent-session")

    def test_load_session(self, opencode_storage_dir: Path) -> None:
        """Test loading a session's conversation history."""
        loader = OpenCodeLoader(history_path=opencode_storage_dir)
        session = loader.get_session_by_id("ses_test123")
        messages = loader.load_session(session)

        assert len(messages) >= 2  # At least user message and assistant message

        # Check first message is user message
        user_msg = messages[0]
        assert isinstance(user_msg, ChatInputUserMessage)
        assert "fix the login" in user_msg.text.lower()

        # Check second message is assistant response
        assistant_msg = messages[1]
        assert isinstance(assistant_msg, ResponseBlockAgentMessage)
        assert assistant_msg.role == "assistant"

    def test_load_session_with_tool_blocks(self, opencode_storage_dir: Path) -> None:
        """Test loading a session with tool use and result blocks."""
        loader = OpenCodeLoader(history_path=opencode_storage_dir)
        messages = loader.load_latest()

        # Find assistant message with tool blocks
        assistant_msgs = [m for m in messages if isinstance(m, ResponseBlockAgentMessage)]
        assert len(assistant_msgs) >= 1

        # Check that we have tool blocks in assistant message
        for msg in assistant_msgs:
            has_tool_use = any(isinstance(b, ToolUseBlock) for b in msg.content)
            has_tool_result = any(isinstance(b, ToolResultBlock) for b in msg.content)
            if has_tool_use or has_tool_result:
                break
        else:
            # At least one message should have tool blocks
            assert any(any(isinstance(b, (ToolUseBlock, ToolResultBlock)) for b in m.content) for m in assistant_msgs)

    def test_load_by_id(self, opencode_storage_dir: Path) -> None:
        """Test load_by_id convenience method."""
        loader = OpenCodeLoader(history_path=opencode_storage_dir)
        messages = loader.load_by_id("ses_test123")

        assert len(messages) >= 2
        assert isinstance(messages[0], ChatInputUserMessage)

    def test_load_latest(self, opencode_storage_dir: Path) -> None:
        """Test load_latest convenience method."""
        loader = OpenCodeLoader(history_path=opencode_storage_dir)
        messages = loader.load_latest()

        assert len(messages) >= 2
        assert isinstance(messages[0], ChatInputUserMessage)


class TestOpenCodeMessageConversion:
    """Tests for OpenCode message conversion."""

    def test_convert_user_message(self, opencode_storage_dir: Path) -> None:
        """Test converting a user message."""
        loader = OpenCodeLoader(history_path=opencode_storage_dir)
        msg_data = {
            "id": "test-msg",
            "sessionID": "ses_test123",
            "role": "user",
            "time": {"created": 1706644036000},
        }
        # Need to create the parts
        parts_dir = opencode_storage_dir / "part" / "test-msg"
        parts_dir.mkdir(parents=True, exist_ok=True)
        with open(parts_dir / "prt_text.json", "w") as f:
            json.dump({"id": "prt_text", "type": "text", "text": "Test message"}, f)

        result = loader._convert_message(msg_data)
        assert len(result) == 1
        assert isinstance(result[0], ChatInputUserMessage)
        assert result[0].text == "Test message"

    def test_convert_assistant_message_with_text(self, opencode_storage_dir: Path) -> None:
        """Test converting an assistant message with text."""
        loader = OpenCodeLoader(history_path=opencode_storage_dir)

        # Load actual messages
        messages = loader.load_latest()
        assistant_msgs = [m for m in messages if isinstance(m, ResponseBlockAgentMessage)]

        assert len(assistant_msgs) >= 1
        # Check at least one has text content
        has_text = any(any(isinstance(b, TextBlock) for b in m.content) for m in assistant_msgs)
        assert has_text

    def test_convert_parts_with_tool_invocation(self, opencode_storage_dir: Path) -> None:
        """Test converting parts with tool invocation."""
        loader = OpenCodeLoader(history_path=opencode_storage_dir)
        parts = [
            {
                "id": "prt_tool",
                "type": "tool-invocation",
                "tool": "read",
                "input": {"filePath": "/test/file.py"},
            }
        ]
        blocks = loader._convert_parts_to_blocks(parts)

        assert len(blocks) == 1
        assert isinstance(blocks[0], ToolUseBlock)
        assert blocks[0].name == "read"
        assert blocks[0].input["filePath"] == "/test/file.py"

    def test_convert_parts_with_tool_result(self, opencode_storage_dir: Path) -> None:
        """Test converting parts with tool result."""
        loader = OpenCodeLoader(history_path=opencode_storage_dir)
        parts = [
            {
                "id": "prt_result",
                "type": "tool-result",
                "tool": "read",
                "output": "file contents here",
                "isError": False,
            }
        ]
        blocks = loader._convert_parts_to_blocks(parts)

        assert len(blocks) == 1
        assert isinstance(blocks[0], ToolResultBlock)
        assert blocks[0].tool_name == "read"
        from vet_history.types import GenericToolContent

        assert isinstance(blocks[0].content, GenericToolContent)
        assert "file contents" in blocks[0].content.text
        assert not blocks[0].is_error

    def test_convert_parts_with_reasoning(self, opencode_storage_dir: Path) -> None:
        """Test converting parts with reasoning/thinking."""
        loader = OpenCodeLoader(history_path=opencode_storage_dir)
        parts = [
            {
                "id": "prt_reasoning",
                "type": "reasoning",
                "thinking": "Let me think about this...",
            }
        ]
        blocks = loader._convert_parts_to_blocks(parts)

        assert len(blocks) == 1
        assert isinstance(blocks[0], TextBlock)
        assert "[Thinking]" in blocks[0].text
        assert "think about this" in blocks[0].text


class TestOpenCodeMultipleSessions:
    """Tests for handling multiple sessions."""

    def test_multiple_sessions_sorted_by_time(self, temp_dir: Path) -> None:
        """Test that sessions are sorted by update time."""
        storage_dir = temp_dir / "storage"

        # Create two sessions with different update times
        for idx, (session_id, update_time) in enumerate(
            [
                ("ses_older", 1706644000000),  # older
                ("ses_newer", 1706644100000),  # newer
            ]
        ):
            session_dir = storage_dir / "session" / f"project-{idx}"
            session_dir.mkdir(parents=True)
            with open(session_dir / f"{session_id}.json", "w") as f:
                json.dump(
                    {
                        "id": session_id,
                        "projectID": f"project-{idx}",
                        "directory": f"/home/user/project{idx}",
                        "title": f"Session {idx}",
                        "time": {"created": 1706644000000, "updated": update_time},
                    },
                    f,
                )

            # Create empty message directory
            msg_dir = storage_dir / "message" / session_id
            msg_dir.mkdir(parents=True)

        loader = OpenCodeLoader(history_path=storage_dir)
        sessions = loader.list_sessions()

        assert len(sessions) == 2
        assert sessions[0].session_id == "ses_newer"  # Newest first
        assert sessions[1].session_id == "ses_older"


class TestOpenCodeEdgeCases:
    """Tests for edge cases and error handling."""

    def test_session_without_messages(self, temp_dir: Path) -> None:
        """Test loading a session that has no messages."""
        storage_dir = temp_dir / "storage"
        session_dir = storage_dir / "session" / "project-abc"
        session_dir.mkdir(parents=True)

        with open(session_dir / "ses_empty.json", "w") as f:
            json.dump(
                {
                    "id": "ses_empty",
                    "projectID": "project-abc",
                    "directory": "/home/user/project",
                    "title": "Empty session",
                    "time": {"created": 1706644000000, "updated": 1706644000000},
                },
                f,
            )

        loader = OpenCodeLoader(history_path=storage_dir)
        messages = loader.load_by_id("ses_empty")

        assert len(messages) == 0

    def test_message_without_parts(self, temp_dir: Path) -> None:
        """Test loading a message that has no parts."""
        storage_dir = temp_dir / "storage"
        session_dir = storage_dir / "session" / "project-abc"
        session_dir.mkdir(parents=True)

        with open(session_dir / "ses_test.json", "w") as f:
            json.dump(
                {
                    "id": "ses_test",
                    "projectID": "project-abc",
                    "directory": "/home/user/project",
                    "title": "Test session",
                    "time": {"created": 1706644000000, "updated": 1706644000000},
                },
                f,
            )

        # Create message without parts
        msg_dir = storage_dir / "message" / "ses_test"
        msg_dir.mkdir(parents=True)
        with open(msg_dir / "msg_noparts.json", "w") as f:
            json.dump(
                {
                    "id": "msg_noparts",
                    "sessionID": "ses_test",
                    "role": "user",
                    "time": {"created": 1706644000000},
                },
                f,
            )

        loader = OpenCodeLoader(history_path=storage_dir)
        messages = loader.load_by_id("ses_test")

        # Message without parts should be skipped
        assert len(messages) == 0

    def test_malformed_session_json_skipped(self, temp_dir: Path) -> None:
        """Test that malformed session JSON files are skipped."""
        storage_dir = temp_dir / "storage"
        session_dir = storage_dir / "session" / "project-abc"
        session_dir.mkdir(parents=True)

        # Write malformed JSON
        with open(session_dir / "ses_bad.json", "w") as f:
            f.write("not valid json")

        # Write valid JSON
        with open(session_dir / "ses_good.json", "w") as f:
            json.dump(
                {
                    "id": "ses_good",
                    "projectID": "project-abc",
                    "directory": "/home/user/project",
                    "title": "Good session",
                    "time": {"created": 1706644000000, "updated": 1706644000000},
                },
                f,
            )

        loader = OpenCodeLoader(history_path=storage_dir)
        sessions = loader.list_sessions()

        # Should only find the valid session
        assert len(sessions) == 1
        assert sessions[0].session_id == "ses_good"

    def test_timestamp_parsing(self, opencode_storage_dir: Path) -> None:
        """Test that timestamps are correctly parsed from milliseconds."""
        loader = OpenCodeLoader(history_path=opencode_storage_dir)
        sessions = loader.list_sessions()

        assert len(sessions) == 1
        session = sessions[0]
        assert session.created_at is not None
        assert session.updated_at is not None
        # Timestamps should be valid datetimes
        assert session.created_at.year >= 2024

    def test_tool_result_with_dict_output(self, opencode_storage_dir: Path) -> None:
        """Test converting tool result with dict output."""
        loader = OpenCodeLoader(history_path=opencode_storage_dir)
        parts = [
            {
                "id": "prt_result",
                "type": "tool-result",
                "tool": "search",
                "output": {"files": ["a.py", "b.py"], "count": 2},
                "isError": False,
            }
        ]
        blocks = loader._convert_parts_to_blocks(parts)

        assert len(blocks) == 1
        assert isinstance(blocks[0], ToolResultBlock)
        # Dict output should be JSON serialized
        from vet_history.types import GenericToolContent

        assert isinstance(blocks[0].content, GenericToolContent)
        assert "files" in blocks[0].content.text
        assert "a.py" in blocks[0].content.text

    def test_tool_result_with_error(self, opencode_storage_dir: Path) -> None:
        """Test converting tool result with error flag."""
        loader = OpenCodeLoader(history_path=opencode_storage_dir)
        parts = [
            {
                "id": "prt_result",
                "type": "tool-result",
                "tool": "read",
                "output": "File not found",
                "isError": True,
            }
        ]
        blocks = loader._convert_parts_to_blocks(parts)

        assert len(blocks) == 1
        assert isinstance(blocks[0], ToolResultBlock)
        assert blocks[0].is_error is True
