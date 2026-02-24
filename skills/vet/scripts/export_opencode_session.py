#!/usr/bin/env python3
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

parser = argparse.ArgumentParser(description="Export OpenCode session history for vet")
parser.add_argument("--session-id", required=True, help="OpenCode session ID (ses_...)")
args = parser.parse_args()

XDG_DATA_HOME = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
DB_PATH = XDG_DATA_HOME / "opencode" / "opencode.db"
STORAGE = XDG_DATA_HOME / "opencode" / "storage"


def emit_messages(role, msg_id, parts):
    if role == "user":
        text = " ".join(p.get("text", "") for p in parts if p.get("type") == "text")
        if text:
            print(json.dumps({"object_type": "ChatInputUserMessage", "text": text}))
    else:
        content = []
        for p in parts:
            if p.get("type") == "text" and p.get("text"):
                content.append(
                    {"object_type": "TextBlock", "type": "text", "text": p["text"]}
                )
        if content:
            print(
                json.dumps(
                    {
                        "object_type": "ResponseBlockAgentMessage",
                        "role": "assistant",
                        "assistant_message_id": msg_id,
                        "content": content,
                    }
                )
            )


def export_from_sqlite(db_path, session_id):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(
            "SELECT id, time_created, data FROM message WHERE session_id = ? ORDER BY time_created ASC",
            (session_id,),
        )
        messages = cursor.fetchall()

        if not messages:
            print(
                f"WARNING: No messages found for session {session_id} in SQLite database",
                file=sys.stderr,
            )
            return

        for msg_row in messages:
            msg_id = msg_row["id"]
            try:
                msg_data = json.loads(msg_row["data"])
            except (json.JSONDecodeError, TypeError) as e:
                print(
                    f"WARNING: Skipping malformed message data for {msg_id}: {e}",
                    file=sys.stderr,
                )
                continue

            role = msg_data.get("role", "user")

            part_cursor = conn.execute(
                "SELECT id, data FROM part WHERE message_id = ? ORDER BY id ASC",
                (msg_id,),
            )

            parts = []
            for part_row in part_cursor:
                try:
                    part_data = json.loads(part_row["data"])
                except (json.JSONDecodeError, TypeError) as e:
                    print(
                        f"WARNING: Skipping malformed part data for part {part_row['id']}: {e}",
                        file=sys.stderr,
                    )
                    continue
                parts.append(part_data)

            emit_messages(role, msg_id, parts)
    finally:
        conn.close()


def export_from_json(storage_dir, session_id):
    msg_dir = storage_dir / "message" / session_id
    part_dir = storage_dir / "part"

    if not msg_dir.exists():
        print(
            f"WARNING: Message directory not found for session {session_id}",
            file=sys.stderr,
        )
        return

    messages = []
    for msg_file in sorted(msg_dir.glob("*.json")):
        try:
            msg = json.loads(msg_file.read_text())
        except json.JSONDecodeError as e:
            print(
                f"WARNING: Skipping malformed message file {msg_file}: {e}",
                file=sys.stderr,
            )
            continue
        messages.append((msg.get("time", {}).get("created", 0), msg))

    for _, msg in sorted(messages, key=lambda x: x[0]):
        msg_id = msg["id"]
        role = msg.get("role", "user")
        msg_part_dir = part_dir / msg_id

        if not msg_part_dir.exists():
            continue

        parts = []
        for part_file in msg_part_dir.glob("*.json"):
            try:
                part = json.loads(part_file.read_text())
            except json.JSONDecodeError as e:
                print(
                    f"WARNING: Skipping malformed part file {part_file}: {e}",
                    file=sys.stderr,
                )
                continue
            parts.append(part)

        emit_messages(role, msg_id, parts)


if DB_PATH.exists():
    export_from_sqlite(DB_PATH, args.session_id)
elif (STORAGE / "message" / args.session_id).exists():
    export_from_json(STORAGE, args.session_id)
else:
    print(
        f"WARNING: No OpenCode data found for session {args.session_id}. "
        f"Checked SQLite database at {DB_PATH} and JSON storage at {STORAGE}.",
        file=sys.stderr,
    )
    sys.exit(0)
