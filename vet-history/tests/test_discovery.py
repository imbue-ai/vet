"""Tests for session discovery utilities."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from vet_history.utils.discovery import (
    encode_project_path,
    decode_project_path,
    find_claude_code_sessions,
    get_claude_code_projects_path,
    get_opencode_storage_path,
    find_opencode_sessions,
    get_codex_sessions_path,
    find_codex_sessions,
    find_codex_session_by_id,
)


class TestProjectPathEncoding:
    """Tests for Claude Code project path encoding."""

    def test_encode_project_path_unix(self) -> None:
        """Test encoding Unix-style paths."""
        path = Path("/home/user/project")
        encoded = encode_project_path(path)
        assert encoded == "-home-user-project"

    def test_encode_project_path_with_multiple_levels(self) -> None:
        """Test encoding paths with many directory levels."""
        path = Path("/home/user/dev/company/project")
        encoded = encode_project_path(path)
        assert encoded == "-home-user-dev-company-project"

    def test_decode_project_path(self) -> None:
        """Test decoding encoded paths."""
        encoded = "-home-user-project"
        decoded = decode_project_path(encoded)
        assert str(decoded) == "/home/user/project"

    def test_encode_decode_roundtrip(self) -> None:
        """Test that encoding and decoding are inverse operations."""
        original = Path("/home/user/project")
        encoded = encode_project_path(original)
        decoded = decode_project_path(encoded)
        # Compare as strings since Path normalization may differ
        assert str(decoded) == str(original)


class TestClaudeCodeDiscovery:
    """Tests for Claude Code session discovery."""

    def test_get_claude_code_projects_path(self) -> None:
        """Test getting Claude Code projects path."""
        path = get_claude_code_projects_path()
        assert path.name == "projects"
        assert ".claude" in str(path)

    def test_find_claude_code_sessions_empty(self, temp_dir: Path) -> None:
        """Test finding sessions when none exist."""
        projects_dir = temp_dir / "projects"
        projects_dir.mkdir()

        with mock.patch(
            "vet_history.utils.discovery.get_claude_code_projects_path",
            return_value=projects_dir,
        ):
            sessions = find_claude_code_sessions()

        assert sessions == []

    def test_find_claude_code_sessions(self, temp_dir: Path) -> None:
        """Test finding Claude Code sessions."""
        projects_dir = temp_dir / "projects"
        project_dir = projects_dir / "-home-user-project"
        project_dir.mkdir(parents=True)

        # Create session files
        (project_dir / "session-1.jsonl").touch()
        (project_dir / "session-2.jsonl").touch()

        with mock.patch(
            "vet_history.utils.discovery.get_claude_code_projects_path",
            return_value=projects_dir,
        ):
            sessions = find_claude_code_sessions()

        assert len(sessions) == 2
        assert all(s.suffix == ".jsonl" for s in sessions)

    def test_find_claude_code_sessions_filtered_by_project(self, temp_dir: Path) -> None:
        """Test finding sessions filtered by project path."""
        projects_dir = temp_dir / "projects"

        # Create sessions for two projects
        project1 = projects_dir / "-home-user-project1"
        project1.mkdir(parents=True)
        (project1 / "session-1.jsonl").touch()

        project2 = projects_dir / "-home-user-project2"
        project2.mkdir(parents=True)
        (project2 / "session-2.jsonl").touch()

        with mock.patch(
            "vet_history.utils.discovery.get_claude_code_projects_path",
            return_value=projects_dir,
        ):
            sessions = find_claude_code_sessions(project_path=Path("/home/user/project1"))

        assert len(sessions) == 1
        assert "project1" in str(sessions[0].parent)

    def test_find_claude_code_sessions_sorted_by_mtime(self, temp_dir: Path) -> None:
        """Test that sessions are sorted by modification time."""
        import time

        projects_dir = temp_dir / "projects"
        project_dir = projects_dir / "-home-user-project"
        project_dir.mkdir(parents=True)

        # Create sessions with different mtimes
        older = project_dir / "older.jsonl"
        older.touch()
        time.sleep(0.01)
        newer = project_dir / "newer.jsonl"
        newer.touch()

        with mock.patch(
            "vet_history.utils.discovery.get_claude_code_projects_path",
            return_value=projects_dir,
        ):
            sessions = find_claude_code_sessions()

        assert len(sessions) == 2
        assert sessions[0].stem == "newer"  # Newest first
        assert sessions[1].stem == "older"


class TestOpenCodeDiscovery:
    """Tests for OpenCode session discovery."""

    def test_get_opencode_storage_path(self) -> None:
        """Test getting OpenCode storage path."""
        path = get_opencode_storage_path()
        assert path.name == "storage"
        assert "opencode" in str(path)

    def test_get_opencode_storage_path_respects_xdg(self, temp_dir: Path) -> None:
        """Test that XDG_DATA_HOME is respected."""
        with mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(temp_dir)}):
            path = get_opencode_storage_path()

        assert str(temp_dir) in str(path)
        assert path.name == "storage"

    def test_find_opencode_sessions_empty(self, temp_dir: Path) -> None:
        """Test finding sessions when none exist."""
        storage_dir = temp_dir / "storage"
        session_dir = storage_dir / "session"
        session_dir.mkdir(parents=True)

        with mock.patch(
            "vet_history.utils.discovery.get_opencode_storage_path",
            return_value=storage_dir,
        ):
            sessions = find_opencode_sessions()

        assert sessions == []

    def test_find_opencode_sessions(self, temp_dir: Path) -> None:
        """Test finding OpenCode sessions."""
        storage_dir = temp_dir / "storage"
        session_dir = storage_dir / "session" / "project-abc"
        session_dir.mkdir(parents=True)

        # Create session files
        (session_dir / "ses_001.json").touch()
        (session_dir / "ses_002.json").touch()

        with mock.patch(
            "vet_history.utils.discovery.get_opencode_storage_path",
            return_value=storage_dir,
        ):
            sessions = find_opencode_sessions()

        assert len(sessions) == 2
        assert all(s.suffix == ".json" for s in sessions)


class TestCodexDiscovery:
    """Tests for Codex CLI session discovery."""

    def test_get_codex_sessions_path(self) -> None:
        """Test getting Codex sessions path."""
        path = get_codex_sessions_path()
        assert path.name == "sessions"
        assert ".codex" in str(path)

    def test_find_codex_sessions_empty(self, temp_dir: Path) -> None:
        """Test finding sessions when none exist."""
        sessions_dir = temp_dir / "sessions"
        sessions_dir.mkdir()

        with mock.patch(
            "vet_history.utils.discovery.get_codex_sessions_path",
            return_value=sessions_dir,
        ):
            sessions = find_codex_sessions()

        assert sessions == []

    def test_find_codex_sessions(self, temp_dir: Path) -> None:
        """Test finding Codex sessions."""
        sessions_dir = temp_dir / "sessions" / "2026" / "01" / "30"
        sessions_dir.mkdir(parents=True)

        # Create session files
        (sessions_dir / "rollout-2026-01-30T10-00-00-session1.jsonl").touch()
        (sessions_dir / "rollout-2026-01-30T12-00-00-session2.jsonl").touch()

        with mock.patch(
            "vet_history.utils.discovery.get_codex_sessions_path",
            return_value=temp_dir / "sessions",
        ):
            sessions = find_codex_sessions()

        assert len(sessions) == 2
        assert all(s.suffix == ".jsonl" for s in sessions)

    def test_find_codex_sessions_across_dates(self, temp_dir: Path) -> None:
        """Test finding sessions across multiple date directories."""
        base_dir = temp_dir / "sessions"

        # Create sessions for different dates
        day1 = base_dir / "2026" / "01" / "29"
        day1.mkdir(parents=True)
        (day1 / "rollout-2026-01-29T10-00-00-session1.jsonl").touch()

        day2 = base_dir / "2026" / "01" / "30"
        day2.mkdir(parents=True)
        (day2 / "rollout-2026-01-30T10-00-00-session2.jsonl").touch()

        with mock.patch("vet_history.utils.discovery.get_codex_sessions_path", return_value=base_dir):
            sessions = find_codex_sessions()

        assert len(sessions) == 2

    def test_find_codex_session_by_id(self, temp_dir: Path) -> None:
        """Test finding a specific Codex session by ID."""
        sessions_dir = temp_dir / "sessions" / "2026" / "01" / "30"
        sessions_dir.mkdir(parents=True)

        session_file = sessions_dir / "rollout-2026-01-30T10-00-00-abc123.jsonl"
        session_file.touch()

        with mock.patch(
            "vet_history.utils.discovery.get_codex_sessions_path",
            return_value=temp_dir / "sessions",
        ):
            found = find_codex_session_by_id("abc123")

        assert found is not None
        assert found == session_file

    def test_find_codex_session_by_id_not_found(self, temp_dir: Path) -> None:
        """Test finding nonexistent Codex session by ID."""
        sessions_dir = temp_dir / "sessions"
        sessions_dir.mkdir()

        with mock.patch(
            "vet_history.utils.discovery.get_codex_sessions_path",
            return_value=sessions_dir,
        ):
            found = find_codex_session_by_id("nonexistent")

        assert found is None
