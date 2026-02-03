"""Claude Code conversation history loader.

Claude Code stores sessions as JSONL files in ~/.claude/projects/<encoded-path>/<session-uuid>.jsonl
Each line is a JSON object with a 'type' field (user, assistant, queue-operation).
"""

from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from vet_history.loaders.base import BaseLoader
from vet_history.loaders.base import LoaderError
from vet_history.loaders.base import SessionNotFoundError
from vet_history.loaders.base import SessionParseError
from vet_history.types import ChatInputUserMessage
from vet_history.types import ConversationMessage
from vet_history.types import GenericToolContent
from vet_history.types import ResponseBlockAgentMessage
from vet_history.types import SessionInfo
from vet_history.types import TextBlock
from vet_history.types import ToolResultBlock
from vet_history.types import ToolUseBlock
from vet_history.utils.discovery import decode_project_path
from vet_history.utils.discovery import find_claude_code_sessions
from vet_history.utils.discovery import get_claude_code_projects_path


class ClaudeCodeLoader(BaseLoader):
    """Loader for Claude Code conversation history."""

    AGENT_NAME = "claude-code"
    DEFAULT_HISTORY_PATH = get_claude_code_projects_path()

    def __init__(self, history_path: Path | None = None):
        """Initialize the Claude Code loader.

        Args:
            history_path: Override the default projects directory path.

        Raises:
            LoaderError: If the history path does not exist.
        """
        if history_path is None:
            history_path = get_claude_code_projects_path()
        if not history_path.exists():
            raise LoaderError(
                f"Claude Code projects directory not found: {history_path}\n"
                "Is Claude Code installed and has it been used?"
            )
        super().__init__(history_path)

    def list_sessions(self, project_path: Path | None = None) -> list[SessionInfo]:
        """List available Claude Code sessions.

        Args:
            project_path: Filter sessions to those associated with this project.

        Returns:
            List of SessionInfo objects.
        """
        session_files = find_claude_code_sessions(project_path, base_path=self.history_path)
        sessions: list[SessionInfo] = []

        for session_file in session_files:
            session_id = session_file.stem  # UUID from filename
            project_dir = session_file.parent.name  # Encoded project path
            decoded_project = decode_project_path(project_dir)

            stat = session_file.stat()
            sessions.append(
                SessionInfo(
                    session_id=session_id,
                    project_path=str(decoded_project),
                    created_at=datetime.datetime.fromtimestamp(stat.st_ctime, tz=datetime.timezone.utc),
                    updated_at=datetime.datetime.fromtimestamp(stat.st_mtime, tz=datetime.timezone.utc),
                    title=None,  # Could extract from session data
                    agent=self.AGENT_NAME,
                )
            )

        return sessions

    def get_latest_session(self, project_path: Path | None = None) -> SessionInfo:
        """Get the most recent Claude Code session.

        Args:
            project_path: Filter to sessions associated with this project.

        Returns:
            SessionInfo for the most recent session.

        Raises:
            SessionNotFoundError: If no sessions are found.
        """
        sessions = self.list_sessions(project_path)
        if not sessions:
            if project_path:
                raise SessionNotFoundError(f"No Claude Code sessions found for project: {project_path}")
            raise SessionNotFoundError("No Claude Code sessions found")
        return sessions[0]  # Already sorted by modification time

    def get_session_by_id(self, session_id: str) -> SessionInfo:
        """Get a specific Claude Code session by ID.

        Args:
            session_id: The session UUID.

        Returns:
            SessionInfo for the requested session.

        Raises:
            SessionNotFoundError: If the session is not found.
        """
        # Search all projects for the session
        if not self.history_path or not self.history_path.exists():
            raise SessionNotFoundError(f"Claude Code history path not found: {self.history_path}")

        for project_dir in self.history_path.iterdir():
            if not project_dir.is_dir():
                continue
            session_file = project_dir / f"{session_id}.jsonl"
            if session_file.exists():
                decoded_project = decode_project_path(project_dir.name)
                stat = session_file.stat()
                return SessionInfo(
                    session_id=session_id,
                    project_path=str(decoded_project),
                    created_at=datetime.datetime.fromtimestamp(stat.st_ctime, tz=datetime.timezone.utc),
                    updated_at=datetime.datetime.fromtimestamp(stat.st_mtime, tz=datetime.timezone.utc),
                    title=None,
                    agent=self.AGENT_NAME,
                )

        raise SessionNotFoundError(f"Claude Code session not found: {session_id}")

    def load_session(self, session: SessionInfo) -> list[ConversationMessage]:
        """Load the conversation history for a Claude Code session.

        Args:
            session: SessionInfo describing the session to load.

        Returns:
            List of ConversationMessage objects.

        Raises:
            SessionParseError: If the session data cannot be parsed.
        """
        if session.project_path is None:
            raise SessionParseError("Session missing project_path")

        # Reconstruct the session file path
        from vet_history.utils.discovery import encode_project_path

        if self.history_path is None:
            raise SessionParseError("History path not set")

        encoded_project = encode_project_path(Path(session.project_path))
        session_file = self.history_path / encoded_project / f"{session.session_id}.jsonl"

        if not session_file.exists():
            raise SessionParseError(f"Session file not found: {session_file}")

        messages: list[ConversationMessage] = []

        try:
            with open(session_file) as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        converted = self._convert_message(data)
                        if converted:
                            messages.append(converted)
                    except json.JSONDecodeError as e:
                        logger.warning(
                            "Skipping malformed JSON at line %d in %s: %s",
                            line_num,
                            session_file,
                            e,
                        )
                        continue
        except OSError as e:
            raise SessionParseError(f"Failed to read session file: {e}") from e

        return messages

    def _convert_message(self, data: dict[str, Any]) -> ConversationMessage | None:
        """Convert a Claude Code message to VET format.

        Args:
            data: Raw message data from JSONL.

        Returns:
            Converted ConversationMessage, or None if message should be skipped.
        """
        msg_type = data.get("type")

        # Skip queue operations and other non-conversation events
        if msg_type not in ("user", "assistant"):
            return None

        timestamp_str = data.get("timestamp")
        timestamp = None
        if timestamp_str:
            try:
                timestamp = datetime.datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except ValueError:
                timestamp = datetime.datetime.now(datetime.timezone.utc)

        message_data = data.get("message", {})
        content_blocks = message_data.get("content", [])

        if msg_type == "user":
            # Check if this is a tool result message
            if data.get("sourceToolAssistantUUID"):
                # This is a tool result, convert to agent message
                return self._convert_tool_result(data, timestamp)

            # Regular user message
            text_parts = []
            for block in content_blocks:
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                elif block.get("type") == "tool_result":
                    # Skip tool results in user messages (handled separately)
                    continue

            if not text_parts:
                return None

            return ChatInputUserMessage(
                message_id=data.get("uuid", ""),
                text="\n".join(text_parts),
                approximate_creation_time=timestamp or datetime.datetime.now(datetime.timezone.utc),
            )

        elif msg_type == "assistant":
            blocks = self._convert_content_blocks(content_blocks)
            if not blocks:
                return None

            return ResponseBlockAgentMessage(
                message_id=data.get("uuid", ""),
                role="assistant",
                assistant_message_id=message_data.get("id", data.get("uuid", "")),
                content=tuple(blocks),
                approximate_creation_time=timestamp or datetime.datetime.now(datetime.timezone.utc),
            )

        return None

    def _convert_tool_result(
        self, data: dict[str, Any], timestamp: datetime.datetime | None
    ) -> ResponseBlockAgentMessage | None:
        """Convert a tool result message to VET format.

        Args:
            data: Raw message data containing tool result.
            timestamp: Message timestamp.

        Returns:
            ResponseBlockAgentMessage with tool result block.
        """
        message_data = data.get("message", {})
        content_blocks = message_data.get("content", [])
        tool_use_result = data.get("toolUseResult", {})

        blocks = []
        for block in content_blocks:
            if block.get("type") == "tool_result":
                tool_use_id = block.get("tool_use_id", "")
                content_text = block.get("content", "")
                is_error = block.get("is_error", False)

                # Try to get more details from toolUseResult
                if tool_use_result:
                    if "stdout" in tool_use_result:
                        content_text = tool_use_result.get("stdout", "")
                        if tool_use_result.get("stderr"):
                            content_text += f"\n[stderr]\n{tool_use_result['stderr']}"
                    elif "file" in tool_use_result:
                        file_info = tool_use_result["file"]
                        content_text = file_info.get("content", content_text)

                blocks.append(
                    ToolResultBlock(
                        tool_use_id=tool_use_id,
                        tool_name="unknown",  # Claude Code doesn't include tool name in result
                        invocation_string="",
                        content=GenericToolContent(text=content_text),
                        is_error=is_error,
                    )
                )

        if not blocks:
            return None

        return ResponseBlockAgentMessage(
            message_id=data.get("uuid", ""),
            role="user",  # Tool results are user role in the API
            assistant_message_id=data.get("uuid", ""),
            content=tuple(blocks),
            approximate_creation_time=timestamp or datetime.datetime.now(datetime.timezone.utc),
        )

    def _convert_content_blocks(self, blocks: list[dict[str, Any]]) -> list[TextBlock | ToolUseBlock]:
        """Convert Claude Code content blocks to VET format.

        Args:
            blocks: List of content block dicts from Claude Code.

        Returns:
            List of VET content blocks.
        """
        result: list[TextBlock | ToolUseBlock] = []

        for block in blocks:
            block_type = block.get("type")

            if block_type == "text":
                text = block.get("text", "")
                if text:
                    result.append(TextBlock(text=text))

            elif block_type == "tool_use":
                result.append(
                    ToolUseBlock(
                        id=block.get("id", ""),
                        name=block.get("name", "unknown"),
                        input=block.get("input", {}),
                    )
                )

        return result
