"""Pytest configuration and shared fixtures for vet-history tests."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Generator

import pytest


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def claude_code_user_message() -> dict:
    """Sample Claude Code user message."""
    return {
        "type": "user",
        "parentUuid": None,
        "isSidechain": False,
        "userType": "external",
        "cwd": "/home/user/project",
        "sessionId": "test-session-123",
        "version": "2.1.22",
        "gitBranch": "main",
        "uuid": "user-msg-001",
        "timestamp": "2026-01-30T20:27:17.084Z",
        "permissionMode": "bypassPermissions",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": "Please fix the bug in the login function"}],
        },
    }


@pytest.fixture
def claude_code_assistant_message() -> dict:
    """Sample Claude Code assistant message with text."""
    return {
        "type": "assistant",
        "parentUuid": "user-msg-001",
        "isSidechain": False,
        "userType": "external",
        "cwd": "/home/user/project",
        "sessionId": "test-session-123",
        "version": "2.1.22",
        "gitBranch": "main",
        "uuid": "assistant-msg-001",
        "timestamp": "2026-01-30T20:27:19.431Z",
        "requestId": "req_123",
        "message": {
            "model": "claude-sonnet-4-5-20250929",
            "id": "msg_123",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "I'll fix the bug in the login function."}],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 100, "output_tokens": 50},
        },
    }


@pytest.fixture
def claude_code_tool_use_message() -> dict:
    """Sample Claude Code assistant message with tool use."""
    return {
        "type": "assistant",
        "parentUuid": "assistant-msg-001",
        "uuid": "tool-use-msg-001",
        "timestamp": "2026-01-30T20:27:20.038Z",
        "sessionId": "test-session-123",
        "message": {
            "model": "claude-sonnet-4-5-20250929",
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_001",
                    "name": "Read",
                    "input": {"filePath": "/home/user/project/login.py"},
                }
            ],
        },
    }


@pytest.fixture
def claude_code_tool_result_message() -> dict:
    """Sample Claude Code tool result message."""
    return {
        "type": "user",
        "parentUuid": "tool-use-msg-001",
        "uuid": "tool-result-msg-001",
        "timestamp": "2026-01-30T20:27:22.396Z",
        "sessionId": "test-session-123",
        "sourceToolAssistantUUID": "tool-use-msg-001",
        "toolUseResult": {
            "stdout": "def login(username, password):\n    pass",
            "stderr": "",
            "interrupted": False,
            "isImage": False,
        },
        "message": {
            "role": "user",
            "content": [
                {
                    "tool_use_id": "toolu_001",
                    "type": "tool_result",
                    "content": "def login(username, password):\n    pass",
                    "is_error": False,
                }
            ],
        },
    }


@pytest.fixture
def claude_code_session_dir(
    temp_dir: Path,
    claude_code_user_message: dict,
    claude_code_assistant_message: dict,
    claude_code_tool_use_message: dict,
    claude_code_tool_result_message: dict,
) -> Path:
    """Create a mock Claude Code session directory structure."""
    # Create projects directory with encoded path
    projects_dir = temp_dir / "projects"
    project_dir = projects_dir / "-home-user-project"
    project_dir.mkdir(parents=True)

    # Create session file
    session_file = project_dir / "test-session-123.jsonl"
    messages = [
        claude_code_user_message,
        claude_code_assistant_message,
        claude_code_tool_use_message,
        claude_code_tool_result_message,
    ]
    with open(session_file, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")

    return projects_dir


# =============================================================================
# OpenCode Fixtures
# =============================================================================


@pytest.fixture
def opencode_session_data() -> dict:
    """Sample OpenCode session metadata."""
    return {
        "id": "ses_test123",
        "slug": "test-session",
        "version": "1.1.35",
        "projectID": "project-abc123",
        "directory": "/home/user/project",
        "title": "Fix login bug",
        "time": {
            "created": 1706644036000,  # 2024-01-30 20:27:16 UTC
            "updated": 1706644100000,
        },
    }


@pytest.fixture
def opencode_user_message_data() -> dict:
    """Sample OpenCode user message."""
    return {
        "id": "msg_user001",
        "sessionID": "ses_test123",
        "role": "user",
        "time": {
            "created": 1706644036000,
        },
        "model": {"providerID": "anthropic", "modelID": "claude-sonnet-4"},
    }


@pytest.fixture
def opencode_user_part_data() -> dict:
    """Sample OpenCode user message part."""
    return {
        "id": "prt_user001_text",
        "sessionID": "ses_test123",
        "messageID": "msg_user001",
        "type": "text",
        "text": "Please fix the login function",
    }


@pytest.fixture
def opencode_assistant_message_data() -> dict:
    """Sample OpenCode assistant message."""
    return {
        "id": "msg_assistant001",
        "sessionID": "ses_test123",
        "role": "assistant",
        "time": {
            "created": 1706644040000,
        },
        "model": {"providerID": "anthropic", "modelID": "claude-sonnet-4"},
    }


@pytest.fixture
def opencode_assistant_text_part() -> dict:
    """Sample OpenCode assistant text part."""
    return {
        "id": "prt_assistant001_text",
        "sessionID": "ses_test123",
        "messageID": "msg_assistant001",
        "type": "text",
        "text": "I'll fix the login function for you.",
    }


@pytest.fixture
def opencode_tool_invocation_part() -> dict:
    """Sample OpenCode tool invocation part."""
    return {
        "id": "prt_assistant001_tool",
        "sessionID": "ses_test123",
        "messageID": "msg_assistant001",
        "type": "tool-invocation",
        "tool": "read",
        "input": {"filePath": "/home/user/project/login.py"},
    }


@pytest.fixture
def opencode_tool_result_part() -> dict:
    """Sample OpenCode tool result part."""
    return {
        "id": "prt_assistant001_result",
        "sessionID": "ses_test123",
        "messageID": "msg_assistant001",
        "type": "tool-result",
        "tool": "read",
        "output": "def login():\n    pass",
        "isError": False,
    }


@pytest.fixture
def opencode_storage_dir(
    temp_dir: Path,
    opencode_session_data: dict,
    opencode_user_message_data: dict,
    opencode_user_part_data: dict,
    opencode_assistant_message_data: dict,
    opencode_assistant_text_part: dict,
    opencode_tool_invocation_part: dict,
    opencode_tool_result_part: dict,
) -> Path:
    """Create a mock OpenCode storage directory structure."""
    storage_dir = temp_dir / "storage"

    # Create session directory
    session_dir = storage_dir / "session" / opencode_session_data["projectID"]
    session_dir.mkdir(parents=True)
    session_file = session_dir / f"{opencode_session_data['id']}.json"
    with open(session_file, "w") as f:
        json.dump(opencode_session_data, f)

    # Create message directory
    message_dir = storage_dir / "message" / opencode_session_data["id"]
    message_dir.mkdir(parents=True)

    # Write user message
    with open(message_dir / f"{opencode_user_message_data['id']}.json", "w") as f:
        json.dump(opencode_user_message_data, f)

    # Write assistant message
    with open(message_dir / f"{opencode_assistant_message_data['id']}.json", "w") as f:
        json.dump(opencode_assistant_message_data, f)

    # Create part directories and files
    user_part_dir = storage_dir / "part" / opencode_user_message_data["id"]
    user_part_dir.mkdir(parents=True)
    with open(user_part_dir / f"{opencode_user_part_data['id']}.json", "w") as f:
        json.dump(opencode_user_part_data, f)

    assistant_part_dir = storage_dir / "part" / opencode_assistant_message_data["id"]
    assistant_part_dir.mkdir(parents=True)
    with open(assistant_part_dir / f"{opencode_assistant_text_part['id']}.json", "w") as f:
        json.dump(opencode_assistant_text_part, f)
    with open(assistant_part_dir / f"{opencode_tool_invocation_part['id']}.json", "w") as f:
        json.dump(opencode_tool_invocation_part, f)
    with open(assistant_part_dir / f"{opencode_tool_result_part['id']}.json", "w") as f:
        json.dump(opencode_tool_result_part, f)

    return storage_dir


# =============================================================================
# Codex CLI Fixtures
# =============================================================================


@pytest.fixture
def codex_session_meta() -> dict:
    """Sample Codex session metadata event."""
    return {
        "timestamp": "2026-01-30T20:27:17.000Z",
        "type": "session_meta",
        "payload": {
            "id": "codex-session-123",
            "timestamp": "2026-01-30T20:27:17.000Z",
            "cwd": "/home/user/project",
            "originator": "codex_cli_rs",
            "cli_version": "0.63.0",
            "source": "cli",
            "model_provider": "openai",
            "git": {"commit_hash": "abc123", "branch": "main"},
        },
    }


@pytest.fixture
def codex_user_message_event() -> dict:
    """Sample Codex user message event."""
    return {
        "timestamp": "2026-01-30T20:27:18.000Z",
        "type": "event_msg",
        "payload": {
            "type": "user_message",
            "message": "Fix the login bug please",
            "images": [],
        },
    }


@pytest.fixture
def codex_response_item_user() -> dict:
    """Sample Codex response_item with user role."""
    return {
        "timestamp": "2026-01-30T20:27:18.500Z",
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "Fix the login bug please"}],
        },
    }


@pytest.fixture
def codex_function_call_event() -> dict:
    """Sample Codex function call event."""
    return {
        "timestamp": "2026-01-30T20:27:19.000Z",
        "type": "response_item",
        "payload": {
            "type": "function_call",
            "name": "shell_command",
            "arguments": '{"command": "cat login.py", "workdir": "/home/user/project"}',
            "call_id": "call_abc123",
        },
    }


@pytest.fixture
def codex_function_output_event() -> dict:
    """Sample Codex function call output event."""
    return {
        "timestamp": "2026-01-30T20:27:20.000Z",
        "type": "response_item",
        "payload": {
            "type": "function_call_output",
            "call_id": "call_abc123",
            "output": "Exit code: 0\nOutput:\ndef login():\n    pass",
        },
    }


@pytest.fixture
def codex_reasoning_event() -> dict:
    """Sample Codex reasoning event."""
    return {
        "timestamp": "2026-01-30T20:27:21.000Z",
        "type": "response_item",
        "payload": {
            "type": "reasoning",
            "summary": [
                {
                    "type": "summary_text",
                    "text": "Reading the login function to understand the bug",
                }
            ],
            "content": None,
            "encrypted_content": None,
        },
    }


@pytest.fixture
def codex_agent_reasoning_event() -> dict:
    """Sample Codex agent_reasoning event_msg."""
    return {
        "timestamp": "2026-01-30T20:27:21.500Z",
        "type": "event_msg",
        "payload": {
            "type": "agent_reasoning",
            "text": "**Analyzing the login function**",
        },
    }


@pytest.fixture
def codex_session_dir(
    temp_dir: Path,
    codex_session_meta: dict,
    codex_user_message_event: dict,
    codex_response_item_user: dict,
    codex_function_call_event: dict,
    codex_function_output_event: dict,
    codex_reasoning_event: dict,
    codex_agent_reasoning_event: dict,
) -> Path:
    """Create a mock Codex CLI session directory structure."""
    # Create sessions directory with date-based structure
    sessions_dir = temp_dir / "sessions" / "2026" / "01" / "30"
    sessions_dir.mkdir(parents=True)

    # Create session file
    session_file = sessions_dir / "rollout-2026-01-30T20-27-17-codex-session-123.jsonl"
    events = [
        codex_session_meta,
        codex_user_message_event,
        codex_response_item_user,
        codex_function_call_event,
        codex_function_output_event,
        codex_reasoning_event,
        codex_agent_reasoning_event,
    ]
    with open(session_file, "w") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    return temp_dir
