"""OpenCode conversation history loader.

OpenCode stores sessions in a file-based storage system at:
~/.local/share/opencode/storage/
  - session/<project-id>/<session-id>.json - Session metadata
  - message/<session-id>/<message-id>.json - Message metadata
  - part/<message-id>/<part-id>.json - Message content parts
"""

from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from typing import Any

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
from vet_history.utils.discovery import get_opencode_storage_path

logger = logging.getLogger(__name__)


class OpenCodeLoader(BaseLoader):
    """Loader for OpenCode conversation history."""

    AGENT_NAME = "opencode"
    DEFAULT_HISTORY_PATH = get_opencode_storage_path()

    def __init__(self, history_path: Path | None = None):
        if history_path is None:
            history_path = get_opencode_storage_path()
        if not history_path.exists():
            raise LoaderError(
                f"OpenCode storage directory not found: {history_path}\n"
                "Is OpenCode installed and has it been used?"
            )
        super().__init__(history_path)

    def _get_sessions_dir(self) -> Path:
        assert self.history_path is not None
        return self.history_path / "session"

    def _get_messages_dir(self) -> Path:
        assert self.history_path is not None
        return self.history_path / "message"

    def _get_parts_dir(self) -> Path:
        assert self.history_path is not None
        return self.history_path / "part"

    def list_sessions(self, project_path: Path | None = None) -> list[SessionInfo]:
        sessions_dir = self._get_sessions_dir()
        if not sessions_dir.exists():
            return []

        sessions: list[SessionInfo] = []

        # Iterate through project directories
        for project_dir in sessions_dir.iterdir():
            if not project_dir.is_dir():
                continue

            # Iterate through session files in each project
            for session_file in project_dir.glob("*.json"):
                try:
                    with open(session_file) as f:
                        session_data = json.load(f)

                    session_id = session_data.get("id", session_file.stem)
                    directory = session_data.get("directory")

                    # Filter by project path if specified
                    if project_path is not None:
                        if directory is None:
                            continue
                        if (
                            not Path(directory)
                            .resolve()
                            .is_relative_to(project_path.resolve())
                        ):
                            continue

                    time_data = session_data.get("time", {})
                    created_at = None
                    updated_at = None

                    if time_data.get("created"):
                        created_at = datetime.datetime.fromtimestamp(
                            time_data["created"] / 1000, tz=datetime.timezone.utc
                        )
                    if time_data.get("updated"):
                        updated_at = datetime.datetime.fromtimestamp(
                            time_data["updated"] / 1000, tz=datetime.timezone.utc
                        )

                    sessions.append(
                        SessionInfo(
                            session_id=session_id,
                            project_path=directory,
                            created_at=created_at,
                            updated_at=updated_at,
                            title=session_data.get("title") or session_data.get("slug"),
                            agent=self.AGENT_NAME,
                        )
                    )
                except (OSError, json.JSONDecodeError) as e:
                    logger.debug("Skipping session file %s: %s", session_file, e)
                    continue

        # Sort by updated_at, newest first
        sessions.sort(
            key=lambda s: s.updated_at
            or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc),
            reverse=True,
        )
        return sessions

    def get_latest_session(self, project_path: Path | None = None) -> SessionInfo:
        sessions = self.list_sessions(project_path)
        if not sessions:
            if project_path:
                raise SessionNotFoundError(
                    f"No OpenCode sessions found for project: {project_path}"
                )
            raise SessionNotFoundError("No OpenCode sessions found")
        return sessions[0]

    def get_session_by_id(self, session_id: str) -> SessionInfo:
        sessions_dir = self._get_sessions_dir()
        if not sessions_dir.exists():
            raise SessionNotFoundError(f"OpenCode session not found: {session_id}")

        # Search all project directories for the session
        for project_dir in sessions_dir.iterdir():
            if not project_dir.is_dir():
                continue

            session_file = project_dir / f"{session_id}.json"
            if session_file.exists():
                try:
                    with open(session_file) as f:
                        session_data = json.load(f)

                    time_data = session_data.get("time", {})
                    created_at = None
                    updated_at = None

                    if time_data.get("created"):
                        created_at = datetime.datetime.fromtimestamp(
                            time_data["created"] / 1000, tz=datetime.timezone.utc
                        )
                    if time_data.get("updated"):
                        updated_at = datetime.datetime.fromtimestamp(
                            time_data["updated"] / 1000, tz=datetime.timezone.utc
                        )

                    return SessionInfo(
                        session_id=session_id,
                        project_path=session_data.get("directory"),
                        created_at=created_at,
                        updated_at=updated_at,
                        title=session_data.get("title") or session_data.get("slug"),
                        agent=self.AGENT_NAME,
                    )
                except (OSError, json.JSONDecodeError) as e:
                    raise SessionParseError(f"Failed to parse session: {e}") from e

        raise SessionNotFoundError(f"OpenCode session not found: {session_id}")

    def load_session(self, session: SessionInfo) -> list[ConversationMessage]:
        messages_dir = self._get_messages_dir() / session.session_id
        if not messages_dir.exists():
            return []

        # Load all messages for this session
        message_files: list[tuple[Path, dict[str, Any]]] = []
        for msg_file in messages_dir.glob("*.json"):
            try:
                with open(msg_file) as f:
                    msg_data = json.load(f)
                message_files.append((msg_file, msg_data))
            except (OSError, json.JSONDecodeError) as e:
                logger.debug("Skipping message file %s: %s", msg_file, e)
                continue

        # Sort by creation time
        message_files.sort(key=lambda x: x[1].get("time", {}).get("created", 0))

        # Convert each message
        messages: list[ConversationMessage] = []
        for msg_file, msg_data in message_files:
            try:
                converted = self._convert_message(msg_data)
                if converted:
                    messages.extend(converted)
            except Exception as e:
                logger.warning(
                    "Failed to convert message from %s: %s",
                    msg_file,
                    e,
                )
                continue

        return messages

    def _convert_message(self, msg_data: dict[str, Any]) -> list[ConversationMessage]:
        message_id = msg_data.get("id", "")
        role = msg_data.get("role", "assistant")

        time_data = msg_data.get("time", {})
        timestamp = None
        if time_data.get("created"):
            timestamp = datetime.datetime.fromtimestamp(
                time_data["created"] / 1000, tz=datetime.timezone.utc
            )

        # Load parts for this message
        parts = self._load_message_parts(message_id)
        if not parts:
            return []

        if role == "user":
            # Extract text content from user message parts
            text_parts = []
            for part in parts:
                if part.get("type") == "text":
                    text = part.get("text", "")
                    if text:
                        text_parts.append(text)

            if not text_parts:
                return []

            return [
                ChatInputUserMessage(
                    message_id=message_id,
                    text="\n".join(text_parts),
                    approximate_creation_time=timestamp
                    or datetime.datetime.now(datetime.timezone.utc),
                )
            ]

        elif role in ("assistant", "system"):
            blocks = self._convert_parts_to_blocks(parts)
            if not blocks:
                return []

            return [
                ResponseBlockAgentMessage(
                    message_id=message_id,
                    role=role,  # type: ignore
                    assistant_message_id=message_id,
                    content=tuple(blocks),
                    approximate_creation_time=timestamp
                    or datetime.datetime.now(datetime.timezone.utc),
                )
            ]

        return []

    def _load_message_parts(self, message_id: str) -> list[dict[str, Any]]:
        parts_dir = self._get_parts_dir() / message_id
        if not parts_dir.exists():
            return []

        parts: list[dict[str, Any]] = []
        for part_file in parts_dir.glob("*.json"):
            try:
                with open(part_file) as f:
                    part_data = json.load(f)
                parts.append(part_data)
            except (OSError, json.JSONDecodeError) as e:
                logger.debug("Skipping part file %s: %s", part_file, e)
                continue

        # Sort by part ID (they appear to be chronologically ordered)
        parts.sort(key=lambda p: p.get("id", ""))
        return parts

    def _convert_parts_to_blocks(
        self, parts: list[dict[str, Any]]
    ) -> list[TextBlock | ToolUseBlock | ToolResultBlock]:
        result: list[TextBlock | ToolUseBlock | ToolResultBlock] = []

        for part in parts:
            part_type = part.get("type")

            if part_type == "text":
                text = part.get("text", "")
                if text:
                    result.append(TextBlock(text=text))

            elif part_type == "tool-invocation":
                tool_id = part.get("id", "")
                tool_name = part.get("tool", "unknown")
                tool_input = part.get("input", {})

                result.append(
                    ToolUseBlock(
                        id=tool_id,
                        name=tool_name,
                        input=tool_input if isinstance(tool_input, dict) else {},
                    )
                )

            elif part_type == "tool-result":
                tool_id = part.get("id", "")
                tool_name = part.get("tool", "unknown")
                content = part.get("output", "")
                is_error = part.get("isError", False)

                # Handle different content types
                if isinstance(content, dict):
                    content_str = json.dumps(content)
                elif isinstance(content, list):
                    content_str = json.dumps(content)
                else:
                    content_str = str(content)

                result.append(
                    ToolResultBlock(
                        tool_use_id=tool_id,
                        tool_name=tool_name,
                        invocation_string="",
                        content=GenericToolContent(text=content_str),
                        is_error=is_error,
                    )
                )

            elif part_type == "reasoning":
                # Chain-of-thought/thinking content
                thinking = part.get("thinking", "") or part.get("text", "")
                if thinking:
                    result.append(TextBlock(text=f"[Thinking]\n{thinking}"))

        return result
