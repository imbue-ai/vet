"""Base class for conversation history loaders."""

from __future__ import annotations

import abc
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vet_history.types import ConversationMessage
    from vet_history.types import SessionInfo


class LoaderError(Exception):
    """Base exception for loader errors."""

    pass


class SessionNotFoundError(LoaderError):
    """Raised when a session cannot be found."""

    pass


class SessionParseError(LoaderError):
    """Raised when a session cannot be parsed."""

    pass


class BaseLoader(abc.ABC):
    """Abstract base class for conversation history loaders.

    Each loader implementation handles a specific coding agent's history format.
    """

    # Name of the agent this loader handles
    AGENT_NAME: str = "unknown"

    # Default location for history storage
    DEFAULT_HISTORY_PATH: Path | None = None

    def __init__(self, history_path: Path | None = None):
        """Initialize the loader.

        Args:
            history_path: Override the default history storage path.
        """
        self.history_path = history_path or self.DEFAULT_HISTORY_PATH
        if self.history_path is None:
            raise LoaderError(f"No history path specified for {self.AGENT_NAME} loader")

    @abc.abstractmethod
    def list_sessions(self, project_path: Path | None = None) -> list[SessionInfo]:
        """List available sessions.

        Args:
            project_path: Filter sessions to those associated with this project.

        Returns:
            List of SessionInfo objects describing available sessions.
        """
        ...

    @abc.abstractmethod
    def get_latest_session(self, project_path: Path | None = None) -> SessionInfo:
        """Get the most recent session.

        Args:
            project_path: Filter to sessions associated with this project.

        Returns:
            SessionInfo for the most recent session.

        Raises:
            SessionNotFoundError: If no sessions are found.
        """
        ...

    @abc.abstractmethod
    def get_session_by_id(self, session_id: str) -> SessionInfo:
        """Get a specific session by ID.

        Args:
            session_id: The unique identifier of the session.

        Returns:
            SessionInfo for the requested session.

        Raises:
            SessionNotFoundError: If the session is not found.
        """
        ...

    @abc.abstractmethod
    def load_session(self, session: SessionInfo) -> list[ConversationMessage]:
        """Load the conversation history for a session.

        Args:
            session: SessionInfo describing the session to load.

        Returns:
            List of ConversationMessage objects.

        Raises:
            SessionParseError: If the session data cannot be parsed.
        """
        ...

    def load_latest(self, project_path: Path | None = None) -> list[ConversationMessage]:
        """Load the most recent session's conversation history.

        Args:
            project_path: Filter to sessions associated with this project.

        Returns:
            List of ConversationMessage objects.
        """
        session = self.get_latest_session(project_path)
        return self.load_session(session)

    def load_by_id(self, session_id: str) -> list[ConversationMessage]:
        """Load a specific session's conversation history.

        Args:
            session_id: The unique identifier of the session.

        Returns:
            List of ConversationMessage objects.
        """
        session = self.get_session_by_id(session_id)
        return self.load_session(session)
