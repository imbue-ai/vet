"""Tests for Codex CLI conversation history loader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vet_history.loaders.codex import CodexLoader
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


class TestCodexLoader:
    """Tests for CodexLoader class."""

    def test_init_with_valid_path(self, codex_session_dir: Path) -> None:
        """Test loader initialization with valid sessions path."""
        sessions_dir = codex_session_dir / "sessions"
        loader = CodexLoader(history_path=sessions_dir)
        assert loader.history_path == sessions_dir
        assert loader.AGENT_NAME == "codex"

    def test_init_with_nonexistent_path(self, temp_dir: Path) -> None:
        """Test loader initialization with nonexistent path raises error."""
        nonexistent = temp_dir / "nonexistent"
        with pytest.raises(LoaderError):
            CodexLoader(history_path=nonexistent)

    def test_list_sessions(self, codex_session_dir: Path) -> None:
        """Test listing available sessions."""
        sessions_dir = codex_session_dir / "sessions"
        loader = CodexLoader(history_path=sessions_dir)
        sessions = loader.list_sessions()

        assert len(sessions) == 1
        session = sessions[0]
        assert session.session_id == "codex-session-123"
        assert session.agent == "codex"

    def test_list_sessions_empty_directory(self, temp_dir: Path) -> None:
        """Test listing sessions when no sessions exist."""
        sessions_dir = temp_dir / "sessions"
        sessions_dir.mkdir()

        loader = CodexLoader(history_path=sessions_dir)
        sessions = loader.list_sessions()
        assert len(sessions) == 0

    def test_get_latest_session(self, codex_session_dir: Path) -> None:
        """Test getting the most recent session."""
        sessions_dir = codex_session_dir / "sessions"
        loader = CodexLoader(history_path=sessions_dir)
        session = loader.get_latest_session()

        assert session.session_id == "codex-session-123"
        assert session.agent == "codex"

    def test_get_latest_session_not_found(self, temp_dir: Path) -> None:
        """Test getting latest session when none exist raises error."""
        sessions_dir = temp_dir / "sessions"
        sessions_dir.mkdir()

        loader = CodexLoader(history_path=sessions_dir)
        with pytest.raises(SessionNotFoundError):
            loader.get_latest_session()

    def test_get_session_by_id(self, codex_session_dir: Path) -> None:
        """Test getting a specific session by ID."""
        sessions_dir = codex_session_dir / "sessions"
        loader = CodexLoader(history_path=sessions_dir)
        session = loader.get_session_by_id("codex-session-123")

        assert session.session_id == "codex-session-123"
        assert session.agent == "codex"

    def test_get_session_by_id_not_found(self, codex_session_dir: Path) -> None:
        """Test getting nonexistent session by ID raises error."""
        sessions_dir = codex_session_dir / "sessions"
        loader = CodexLoader(history_path=sessions_dir)
        with pytest.raises(SessionNotFoundError):
            loader.get_session_by_id("nonexistent-session")

    def test_load_session(self, codex_session_dir: Path) -> None:
        """Test loading a session's conversation history."""
        sessions_dir = codex_session_dir / "sessions"
        loader = CodexLoader(history_path=sessions_dir)
        session = loader.get_session_by_id("codex-session-123")
        messages = loader.load_session(session)

        assert len(messages) >= 1

        # Should have user message
        user_msgs = [m for m in messages if isinstance(m, ChatInputUserMessage)]
        assert len(user_msgs) >= 1
        assert "login bug" in user_msgs[0].text.lower()

    def test_load_session_with_function_call(self, codex_session_dir: Path) -> None:
        """Test loading a session with function call events."""
        sessions_dir = codex_session_dir / "sessions"
        loader = CodexLoader(history_path=sessions_dir)
        messages = loader.load_latest()

        # Find function call message
        tool_use_msgs = [
            m
            for m in messages
            if isinstance(m, ResponseBlockAgentMessage) and any(isinstance(b, ToolUseBlock) for b in m.content)
        ]
        assert len(tool_use_msgs) >= 1

        tool_msg = tool_use_msgs[0]
        tool_block = next(b for b in tool_msg.content if isinstance(b, ToolUseBlock))
        assert tool_block.name == "shell_command"
        assert "command" in tool_block.input

    def test_load_session_with_function_output(self, codex_session_dir: Path) -> None:
        """Test loading a session with function output events."""
        sessions_dir = codex_session_dir / "sessions"
        loader = CodexLoader(history_path=sessions_dir)
        messages = loader.load_latest()

        # Find function output message
        tool_result_msgs = [
            m
            for m in messages
            if isinstance(m, ResponseBlockAgentMessage) and any(isinstance(b, ToolResultBlock) for b in m.content)
        ]
        assert len(tool_result_msgs) >= 1

        result_msg = tool_result_msgs[0]
        result_block = next(b for b in result_msg.content if isinstance(b, ToolResultBlock))
        assert result_block.tool_use_id == "call_abc123"

    def test_load_session_with_reasoning(self, codex_session_dir: Path) -> None:
        """Test loading a session with reasoning events."""
        sessions_dir = codex_session_dir / "sessions"
        loader = CodexLoader(history_path=sessions_dir)
        messages = loader.load_latest()

        # Find reasoning message (converted to TextBlock with [Reasoning])
        reasoning_msgs = [
            m
            for m in messages
            if isinstance(m, ResponseBlockAgentMessage)
            and any(isinstance(b, TextBlock) and "[Reasoning]" in b.text for b in m.content)
        ]
        assert len(reasoning_msgs) >= 1

    def test_load_by_id(self, codex_session_dir: Path) -> None:
        """Test load_by_id convenience method."""
        sessions_dir = codex_session_dir / "sessions"
        loader = CodexLoader(history_path=sessions_dir)
        messages = loader.load_by_id("codex-session-123")

        assert len(messages) >= 1

    def test_load_latest(self, codex_session_dir: Path) -> None:
        """Test load_latest convenience method."""
        sessions_dir = codex_session_dir / "sessions"
        loader = CodexLoader(history_path=sessions_dir)
        messages = loader.load_latest()

        assert len(messages) >= 1


class TestCodexEventConversion:
    """Tests for Codex event conversion."""

    def test_convert_user_message_event(self, codex_session_dir: Path, codex_user_message_event: dict) -> None:
        """Test converting a user_message event."""
        sessions_dir = codex_session_dir / "sessions"
        loader = CodexLoader(history_path=sessions_dir)
        result = loader._convert_event(codex_user_message_event)

        assert result is not None
        assert isinstance(result, ChatInputUserMessage)
        assert "login bug" in result.text.lower()

    def test_convert_response_item_user(self, codex_session_dir: Path, codex_response_item_user: dict) -> None:
        """Test converting a response_item with user role."""
        sessions_dir = codex_session_dir / "sessions"
        loader = CodexLoader(history_path=sessions_dir)
        result = loader._convert_event(codex_response_item_user)

        assert result is not None
        assert isinstance(result, ChatInputUserMessage)
        assert "login bug" in result.text.lower()

    def test_convert_function_call_event(self, codex_session_dir: Path, codex_function_call_event: dict) -> None:
        """Test converting a function_call event."""
        sessions_dir = codex_session_dir / "sessions"
        loader = CodexLoader(history_path=sessions_dir)
        result = loader._convert_event(codex_function_call_event)

        assert result is not None
        assert isinstance(result, ResponseBlockAgentMessage)
        assert result.role == "assistant"
        assert len(result.content) == 1
        assert isinstance(result.content[0], ToolUseBlock)
        assert result.content[0].name == "shell_command"

    def test_convert_function_output_event(self, codex_session_dir: Path, codex_function_output_event: dict) -> None:
        """Test converting a function_call_output event."""
        sessions_dir = codex_session_dir / "sessions"
        loader = CodexLoader(history_path=sessions_dir)
        result = loader._convert_event(codex_function_output_event)

        assert result is not None
        assert isinstance(result, ResponseBlockAgentMessage)
        assert result.role == "user"  # Tool results are user role
        assert len(result.content) == 1
        assert isinstance(result.content[0], ToolResultBlock)
        assert result.content[0].tool_use_id == "call_abc123"

    def test_convert_reasoning_event(self, codex_session_dir: Path, codex_reasoning_event: dict) -> None:
        """Test converting a reasoning event."""
        sessions_dir = codex_session_dir / "sessions"
        loader = CodexLoader(history_path=sessions_dir)
        result = loader._convert_event(codex_reasoning_event)

        assert result is not None
        assert isinstance(result, ResponseBlockAgentMessage)
        assert len(result.content) == 1
        assert isinstance(result.content[0], TextBlock)
        assert "[Reasoning]" in result.content[0].text

    def test_convert_agent_reasoning_event(self, codex_session_dir: Path, codex_agent_reasoning_event: dict) -> None:
        """Test converting an agent_reasoning event_msg."""
        sessions_dir = codex_session_dir / "sessions"
        loader = CodexLoader(history_path=sessions_dir)
        result = loader._convert_event(codex_agent_reasoning_event)

        assert result is not None
        assert isinstance(result, ResponseBlockAgentMessage)
        assert isinstance(result.content[0], TextBlock)
        assert "[Reasoning]" in result.content[0].text

    def test_convert_session_meta_skipped(self, codex_session_dir: Path, codex_session_meta: dict) -> None:
        """Test that session_meta events are skipped."""
        sessions_dir = codex_session_dir / "sessions"
        loader = CodexLoader(history_path=sessions_dir)
        result = loader._convert_event(codex_session_meta)

        assert result is None

    def test_convert_turn_events_skipped(self, codex_session_dir: Path) -> None:
        """Test that turn.started and turn.completed events are skipped."""
        sessions_dir = codex_session_dir / "sessions"
        loader = CodexLoader(history_path=sessions_dir)

        turn_started = {
            "timestamp": "2026-01-30T20:27:17.000Z",
            "type": "turn_context",
            "payload": {},
        }
        result = loader._convert_event(turn_started)
        assert result is None


class TestCodexMultipleSessions:
    """Tests for handling multiple sessions."""

    def test_multiple_sessions_sorted_by_time(self, temp_dir: Path) -> None:
        """Test that sessions are sorted by modification time."""
        sessions_dir = temp_dir / "sessions" / "2026" / "01" / "30"
        sessions_dir.mkdir(parents=True)

        # Create older session
        older_session = sessions_dir / "rollout-2026-01-30T10-00-00-older-session.jsonl"
        with open(older_session, "w") as f:
            f.write(
                json.dumps(
                    {
                        "timestamp": "2026-01-30T10:00:00.000Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "user_message",
                            "message": "older",
                            "images": [],
                        },
                    }
                )
                + "\n"
            )

        # Create newer session and touch to make it newer
        newer_session = sessions_dir / "rollout-2026-01-30T12-00-00-newer-session.jsonl"
        with open(newer_session, "w") as f:
            f.write(
                json.dumps(
                    {
                        "timestamp": "2026-01-30T12:00:00.000Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "user_message",
                            "message": "newer",
                            "images": [],
                        },
                    }
                )
                + "\n"
            )

        import time

        time.sleep(0.01)  # Ensure different mtime
        newer_session.touch()

        loader = CodexLoader(history_path=temp_dir / "sessions")
        sessions = loader.list_sessions()

        assert len(sessions) == 2
        assert sessions[0].session_id == "newer-session"  # Newest first
        assert sessions[1].session_id == "older-session"

    def test_session_title_extracted_from_user_message(self, temp_dir: Path) -> None:
        """Test that session title is extracted from first user message."""
        sessions_dir = temp_dir / "sessions" / "2026" / "01" / "30"
        sessions_dir.mkdir(parents=True)

        session_file = sessions_dir / "rollout-2026-01-30T10-00-00-test-session.jsonl"
        with open(session_file, "w") as f:
            f.write(
                json.dumps(
                    {
                        "timestamp": "2026-01-30T10:00:00.000Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "user_message",
                            "message": "This is my first message about testing",
                            "images": [],
                        },
                    }
                )
                + "\n"
            )

        loader = CodexLoader(history_path=temp_dir / "sessions")
        sessions = loader.list_sessions()

        assert len(sessions) == 1
        assert sessions[0].title is not None
        assert "first message" in sessions[0].title


class TestCodexEdgeCases:
    """Tests for edge cases and error handling."""

    def test_malformed_json_line_skipped(self, temp_dir: Path) -> None:
        """Test that malformed JSON lines are skipped gracefully."""
        sessions_dir = temp_dir / "sessions" / "2026" / "01" / "30"
        sessions_dir.mkdir(parents=True)

        session_file = sessions_dir / "rollout-2026-01-30T10-00-00-test-session.jsonl"
        with open(session_file, "w") as f:
            f.write("not valid json\n")
            f.write(
                json.dumps(
                    {
                        "timestamp": "2026-01-30T10:00:00.000Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "user_message",
                            "message": "valid",
                            "images": [],
                        },
                    }
                )
                + "\n"
            )

        loader = CodexLoader(history_path=temp_dir / "sessions")
        messages = loader.load_latest()

        # Should have loaded the valid message, skipped the malformed one
        assert len(messages) == 1
        assert isinstance(messages[0], ChatInputUserMessage)
        assert messages[0].text == "valid"

    def test_empty_session_file(self, temp_dir: Path) -> None:
        """Test handling of empty session files."""
        sessions_dir = temp_dir / "sessions" / "2026" / "01" / "30"
        sessions_dir.mkdir(parents=True)

        session_file = sessions_dir / "rollout-2026-01-30T10-00-00-empty-session.jsonl"
        session_file.touch()

        loader = CodexLoader(history_path=temp_dir / "sessions")
        messages = loader.load_latest()

        assert len(messages) == 0

    def test_timestamp_parsing(self, codex_session_dir: Path) -> None:
        """Test that timestamps are correctly parsed."""
        sessions_dir = codex_session_dir / "sessions"
        loader = CodexLoader(history_path=sessions_dir)
        messages = loader.load_latest()

        for msg in messages:
            assert msg.approximate_creation_time is not None
            assert msg.approximate_creation_time.year >= 2024

    def test_function_call_with_invalid_json_arguments(self, temp_dir: Path) -> None:
        """Test handling function calls with invalid JSON arguments."""
        sessions_dir = temp_dir / "sessions" / "2026" / "01" / "30"
        sessions_dir.mkdir(parents=True)

        session_file = sessions_dir / "rollout-2026-01-30T10-00-00-test-session.jsonl"
        with open(session_file, "w") as f:
            f.write(
                json.dumps(
                    {
                        "timestamp": "2026-01-30T10:00:00.000Z",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "name": "test_func",
                            "arguments": "not valid json",
                            "call_id": "call_123",
                        },
                    }
                )
                + "\n"
            )

        loader = CodexLoader(history_path=temp_dir / "sessions")
        messages = loader.load_latest()

        assert len(messages) == 1
        assert isinstance(messages[0], ResponseBlockAgentMessage)
        tool_block = messages[0].content[0]
        assert isinstance(tool_block, ToolUseBlock)
        # Invalid JSON should be stored as raw value
        assert "raw" in tool_block.input
        assert tool_block.input["raw"] == "not valid json"

    def test_session_id_extraction_patterns(self, temp_dir: Path) -> None:
        """Test session ID extraction from various filename patterns."""
        sessions_dir = temp_dir / "sessions" / "2026" / "01" / "30"
        sessions_dir.mkdir(parents=True)

        # Standard pattern
        session_file = sessions_dir / "rollout-2026-01-30T10-00-00-abc123-def456.jsonl"
        with open(session_file, "w") as f:
            f.write(
                json.dumps(
                    {
                        "timestamp": "2026-01-30T10:00:00.000Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "user_message",
                            "message": "test",
                            "images": [],
                        },
                    }
                )
                + "\n"
            )

        loader = CodexLoader(history_path=temp_dir / "sessions")
        sessions = loader.list_sessions()

        assert len(sessions) == 1
        # Should extract last part as session ID
        assert "def456" in sessions[0].session_id or "abc123" in sessions[0].session_id
