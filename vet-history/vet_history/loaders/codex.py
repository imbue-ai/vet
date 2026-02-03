"""Codex CLI conversation history loader.

Codex CLI stores sessions as JSONL files in ~/.codex/sessions/YYYY/MM/DD/
Each file is named rollout-<timestamp>-<session-id>.jsonl
"""

from __future__ import annotations

import datetime
import json
import logging
import re
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
from vet_history.utils.discovery import find_codex_session_by_id
from vet_history.utils.discovery import find_codex_sessions
from vet_history.utils.discovery import get_codex_sessions_path


class CodexLoader(BaseLoader):
    """Loader for Codex CLI conversation history."""

    AGENT_NAME = "codex"
    DEFAULT_HISTORY_PATH = get_codex_sessions_path()

    # Regex to extract session ID from filename
    # Format: rollout-<timestamp>-<session-id>.jsonl
    SESSION_FILE_PATTERN = re.compile(r"rollout-[\d\-T]+-([\w-]+)\.jsonl")

    def __init__(self, history_path: Path | None = None):
        """Initialize the Codex loader.

        Args:
            history_path: Override the default sessions directory path.

        Raises:
            LoaderError: If the history path does not exist.
        """
        if history_path is None:
            history_path = get_codex_sessions_path()
        if not history_path.exists():
            raise LoaderError(
                f"Codex CLI sessions directory not found: {history_path}\n"
                "Is Codex CLI installed and has it been used?"
            )
        super().__init__(history_path)

    def _extract_session_id_from_path(self, session_file: Path) -> str | None:
        """Extract session ID from a session file path.

        Args:
            session_file: Path to the session JSONL file.

        Returns:
            Session ID or None if the filename doesn't match expected pattern.
        """
        match = self.SESSION_FILE_PATTERN.match(session_file.name)
        if match:
            return match.group(1)
        # Fallback: use the stem after the last dash
        parts = session_file.stem.split("-")
        if len(parts) > 1:
            return parts[-1]
        return session_file.stem

    def list_sessions(self, project_path: Path | None = None) -> list[SessionInfo]:
        """List available Codex sessions.

        Args:
            project_path: Not used for Codex (sessions are stored globally).

        Returns:
            List of SessionInfo objects, sorted by modification time (newest first).
        """
        session_files = find_codex_sessions(base_path=self.history_path)
        sessions: list[SessionInfo] = []

        for session_file in session_files:
            session_id = self._extract_session_id_from_path(session_file)
            if not session_id:
                continue

            stat = session_file.stat()

            # Try to extract more info from the session file
            title = None
            try:
                with open(session_file) as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        data = json.loads(line)
                        # Look for first user message as title
                        if data.get("type") == "event_msg":
                            payload = data.get("payload", {})
                            if payload.get("type") == "user_message":
                                title = payload.get("message", "")[:100]
                                break
                        elif data.get("type") == "response_item":
                            payload = data.get("payload", {})
                            if payload.get("role") == "user":
                                content = payload.get("content", [])
                                for block in content:
                                    if block.get("type") == "input_text":
                                        title = block.get("text", "")[:100]
                                        break
                        if title:
                            break
            except (OSError, json.JSONDecodeError) as e:
                logger.debug(
                    "Failed to extract title from session file %s: %s", session_file, e
                )

            sessions.append(
                SessionInfo(
                    session_id=session_id,
                    project_path=None,  # Could extract from session_meta if needed
                    created_at=datetime.datetime.fromtimestamp(
                        stat.st_ctime, tz=datetime.timezone.utc
                    ),
                    updated_at=datetime.datetime.fromtimestamp(
                        stat.st_mtime, tz=datetime.timezone.utc
                    ),
                    title=title,
                    agent=self.AGENT_NAME,
                )
            )

        return sessions

    def get_latest_session(self, project_path: Path | None = None) -> SessionInfo:
        """Get the most recent Codex session.

        Args:
            project_path: Not used for Codex.

        Returns:
            SessionInfo for the most recent session.

        Raises:
            SessionNotFoundError: If no sessions are found.
        """
        sessions = self.list_sessions()
        if not sessions:
            raise SessionNotFoundError("No Codex CLI sessions found")
        return sessions[0]  # Already sorted by modification time

    def get_session_by_id(self, session_id: str) -> SessionInfo:
        """Get a specific Codex session by ID.

        Args:
            session_id: The session ID (UUID).

        Returns:
            SessionInfo for the requested session.

        Raises:
            SessionNotFoundError: If the session is not found.
        """
        session_file = find_codex_session_by_id(session_id, base_path=self.history_path)
        if not session_file:
            raise SessionNotFoundError(f"Codex session not found: {session_id}")

        stat = session_file.stat()
        return SessionInfo(
            session_id=session_id,
            project_path=None,
            created_at=datetime.datetime.fromtimestamp(
                stat.st_ctime, tz=datetime.timezone.utc
            ),
            updated_at=datetime.datetime.fromtimestamp(
                stat.st_mtime, tz=datetime.timezone.utc
            ),
            title=None,
            agent=self.AGENT_NAME,
        )

    def _find_session_file(self, session_id: str) -> Path | None:
        """Find the session file for a given session ID.

        Args:
            session_id: The session ID.

        Returns:
            Path to the session file, or None if not found.
        """
        return find_codex_session_by_id(session_id, base_path=self.history_path)

    def load_session(self, session: SessionInfo) -> list[ConversationMessage]:
        """Load the conversation history for a Codex session.

        Args:
            session: SessionInfo describing the session to load.

        Returns:
            List of ConversationMessage objects.

        Raises:
            SessionParseError: If the session data cannot be parsed.
        """
        session_file = self._find_session_file(session.session_id)
        if not session_file:
            raise SessionParseError(f"Session file not found for: {session.session_id}")

        messages: list[ConversationMessage] = []
        thread_id: str | None = None

        try:
            with open(session_file) as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)

                        # Extract thread_id from thread.started event
                        if data.get("type") == "thread.started":
                            thread_id = data.get("thread_id")
                            continue

                        converted = self._convert_event(data)
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

    def _convert_event(self, data: dict[str, Any]) -> ConversationMessage | None:
        """Convert a Codex event to VET format.

        Args:
            data: Raw event data from JSONL.

        Returns:
            Converted ConversationMessage, or None if event should be skipped.
        """
        event_type = data.get("type")
        timestamp_str = data.get("timestamp")

        timestamp = None
        if timestamp_str:
            try:
                timestamp = datetime.datetime.fromisoformat(
                    timestamp_str.replace("Z", "+00:00")
                )
            except ValueError:
                timestamp = datetime.datetime.now(datetime.timezone.utc)

        # Handle different event types
        if event_type == "event_msg":
            return self._convert_event_msg(data, timestamp)
        elif event_type == "response_item":
            return self._convert_response_item(data, timestamp)
        elif event_type in (
            "turn.started",
            "turn.completed",
            "turn_context",
            "session_meta",
        ):
            # Skip metadata events
            return None

        return None

    def _convert_event_msg(
        self, data: dict[str, Any], timestamp: datetime.datetime | None
    ) -> ConversationMessage | None:
        """Convert a Codex event_msg to VET format.

        Args:
            data: Event data.
            timestamp: Event timestamp.

        Returns:
            Converted message or None.
        """
        payload = data.get("payload", {})
        msg_type = payload.get("type")

        if msg_type == "user_message":
            text = payload.get("message", "")
            if not text:
                return None

            return ChatInputUserMessage(
                text=text,
                approximate_creation_time=timestamp
                or datetime.datetime.now(datetime.timezone.utc),
            )

        elif msg_type == "agent_reasoning":
            # Reasoning/thinking content
            text = payload.get("text", "")
            if not text:
                return None

            return ResponseBlockAgentMessage(
                role="assistant",
                content=(TextBlock(text=f"[Reasoning] {text}"),),
                approximate_creation_time=timestamp
                or datetime.datetime.now(datetime.timezone.utc),
            )

        return None

    def _convert_response_item(
        self, data: dict[str, Any], timestamp: datetime.datetime | None
    ) -> ConversationMessage | None:
        """Convert a Codex response_item to VET format.

        Args:
            data: Event data.
            timestamp: Event timestamp.

        Returns:
            Converted message or None.
        """
        payload = data.get("payload", {})
        item_type = payload.get("type")

        if item_type == "message":
            role = payload.get("role", "assistant")
            content_blocks = payload.get("content", [])

            if role == "user":
                # User message
                text_parts = []
                for block in content_blocks:
                    if block.get("type") == "input_text":
                        text_parts.append(block.get("text", ""))

                if not text_parts:
                    return None

                return ChatInputUserMessage(
                    text="\n".join(text_parts),
                    approximate_creation_time=timestamp
                    or datetime.datetime.now(datetime.timezone.utc),
                )
            else:
                # Assistant message
                blocks = self._convert_content_blocks(content_blocks)
                if not blocks:
                    return None

                return ResponseBlockAgentMessage(
                    role="assistant",
                    content=tuple(blocks),
                    approximate_creation_time=timestamp
                    or datetime.datetime.now(datetime.timezone.utc),
                )

        elif item_type == "function_call":
            # Tool invocation
            name = payload.get("name", "unknown")
            arguments = payload.get("arguments", "{}")
            call_id = payload.get("call_id", "")

            try:
                args = json.loads(arguments) if arguments else {}
            except json.JSONDecodeError:
                args = {"raw": arguments}

            return ResponseBlockAgentMessage(
                role="assistant",
                content=(
                    ToolUseBlock(
                        id=call_id,
                        name=name,
                        input=args,
                    ),
                ),
                approximate_creation_time=timestamp
                or datetime.datetime.now(datetime.timezone.utc),
            )

        elif item_type == "function_call_output":
            # Tool result
            call_id = payload.get("call_id", "")
            output = payload.get("output", "")

            return ResponseBlockAgentMessage(
                role="user",  # Tool results are user role
                content=(
                    ToolResultBlock(
                        tool_use_id=call_id,
                        tool_name="function",
                        invocation_string="",
                        content=GenericToolContent(text=output),
                        is_error=False,  # Codex doesn't seem to have explicit error flag
                    ),
                ),
                approximate_creation_time=timestamp
                or datetime.datetime.now(datetime.timezone.utc),
            )

        elif item_type == "reasoning":
            # Agent reasoning/thinking
            summary = payload.get("summary", [])
            text_parts = []
            for item in summary:
                if item.get("type") == "summary_text":
                    text_parts.append(item.get("text", ""))

            if not text_parts:
                return None

            return ResponseBlockAgentMessage(
                role="assistant",
                content=(TextBlock(text=f"[Reasoning]\n" + "\n".join(text_parts)),),
                approximate_creation_time=timestamp
                or datetime.datetime.now(datetime.timezone.utc),
            )

        return None

    def _convert_content_blocks(
        self, blocks: list[dict[str, Any]]
    ) -> list[TextBlock | ToolUseBlock]:
        """Convert Codex content blocks to VET format.

        Args:
            blocks: List of content block dicts.

        Returns:
            List of VET content blocks.
        """
        result: list[TextBlock | ToolUseBlock] = []

        for block in blocks:
            block_type = block.get("type")

            if block_type == "output_text":
                text = block.get("text", "")
                if text:
                    result.append(TextBlock(text=text))

            elif block_type == "input_text":
                # User input - shouldn't be in assistant messages but handle anyway
                text = block.get("text", "")
                if text:
                    result.append(TextBlock(text=text))

        return result
