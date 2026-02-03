"""Session discovery utilities for various coding agents."""

from __future__ import annotations

import os
from pathlib import Path


def get_home_dir() -> Path:
    """Get the user's home directory."""
    return Path.home()


# =============================================================================
# Claude Code Discovery
# =============================================================================


def get_claude_code_base_path() -> Path:
    """Get the base path for Claude Code history storage."""
    return get_home_dir() / ".claude"


def get_claude_code_projects_path() -> Path:
    """Get the path to Claude Code projects directory."""
    return get_claude_code_base_path() / "projects"


def encode_project_path(project_path: Path) -> str:
    """Encode a project path for Claude Code directory naming.

    Claude Code encodes paths by replacing '/' with '-'.
    Example: /home/andrew/gitRepos/project -> -home-andrew-gitRepos-project

    Args:
        project_path: The absolute path to the project.

    Returns:
        The encoded path string suitable for directory names.
    """
    # Resolve to absolute path
    abs_path = project_path.resolve()
    # Replace path separators with dashes
    return str(abs_path).replace("/", "-").replace("\\", "-")


def decode_project_path(encoded_path: str) -> Path:
    """Decode a Claude Code encoded project path.

    Args:
        encoded_path: The encoded path string (e.g., "-home-andrew-project")

    Returns:
        The decoded Path object.
    """
    # The first character should be a dash (from root /)
    if encoded_path.startswith("-"):
        decoded = "/" + encoded_path[1:].replace("-", "/")
    else:
        decoded = encoded_path.replace("-", "/")
    return Path(decoded)


def find_claude_code_sessions(
    project_path: Path | None = None,
    base_path: Path | None = None,
) -> list[Path]:
    """Find Claude Code session files.

    Args:
        project_path: If provided, only find sessions for this project.
        base_path: Override the default projects directory path.

    Returns:
        List of paths to session JSONL files, sorted by modification time (newest first).
    """
    projects_dir = base_path if base_path is not None else get_claude_code_projects_path()
    if not projects_dir.exists():
        return []

    session_files: list[Path] = []

    if project_path is not None:
        # Find sessions for a specific project
        encoded = encode_project_path(project_path)
        project_dir = projects_dir / encoded
        if project_dir.exists():
            session_files = list(project_dir.glob("*.jsonl"))
    else:
        # Find all sessions across all projects
        for project_dir in projects_dir.iterdir():
            if project_dir.is_dir():
                session_files.extend(project_dir.glob("*.jsonl"))

    # Sort by modification time, newest first
    session_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return session_files


# =============================================================================
# OpenCode Discovery
# =============================================================================


def get_opencode_storage_path() -> Path:
    """Get the OpenCode storage directory path.

    OpenCode uses XDG base directory spec:
    $XDG_DATA_HOME/opencode/storage (defaults to ~/.local/share/opencode/storage)
    """
    xdg_data = os.environ.get("XDG_DATA_HOME", str(get_home_dir() / ".local" / "share"))
    return Path(xdg_data) / "opencode" / "storage"


def find_opencode_sessions(base_path: Path | None = None) -> list[Path]:
    """Find OpenCode session files.

    Args:
        base_path: Override the default storage directory path.

    Returns:
        List of paths to session JSON files, sorted by modification time (newest first).
    """
    storage_dir = base_path if base_path is not None else get_opencode_storage_path()
    sessions_dir = storage_dir / "session"

    if not sessions_dir.exists():
        return []

    session_files: list[Path] = []
    for project_dir in sessions_dir.iterdir():
        if project_dir.is_dir():
            session_files.extend(project_dir.glob("*.json"))

    # Sort by modification time, newest first
    session_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return session_files


# =============================================================================
# Codex CLI Discovery
# =============================================================================


def get_codex_base_path() -> Path:
    """Get the base path for Codex CLI history storage."""
    return get_home_dir() / ".codex"


def get_codex_sessions_path() -> Path:
    """Get the path to Codex sessions directory."""
    return get_codex_base_path() / "sessions"


def find_codex_sessions(base_path: Path | None = None) -> list[Path]:
    """Find Codex CLI session files.

    Codex stores sessions in a date-based directory structure:
    ~/.codex/sessions/YYYY/MM/DD/rollout-<timestamp>-<session-id>.jsonl

    Args:
        base_path: Override the default sessions directory path.

    Returns:
        List of paths to session JSONL files, sorted by modification time (newest first).
    """
    sessions_dir = base_path if base_path is not None else get_codex_sessions_path()
    if not sessions_dir.exists():
        return []

    # Find all .jsonl files recursively
    session_files = list(sessions_dir.rglob("*.jsonl"))

    # Sort by modification time, newest first
    session_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return session_files


def find_codex_session_by_id(
    session_id: str,
    base_path: Path | None = None,
) -> Path | None:
    """Find a Codex session file by session ID.

    Args:
        session_id: The session UUID to search for.
        base_path: Override the default sessions directory path.

    Returns:
        Path to the session file, or None if not found.
    """
    sessions_dir = base_path if base_path is not None else get_codex_sessions_path()
    if not sessions_dir.exists():
        return None

    # Session files are named rollout-<timestamp>-<session-id>.jsonl
    # Search for files containing the session ID
    for session_file in sessions_dir.rglob(f"*{session_id}*.jsonl"):
        return session_file

    return None
