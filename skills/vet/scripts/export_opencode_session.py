#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

parser = argparse.ArgumentParser(description="Export OpenCode session history for vet")
parser.add_argument("--session-id", required=True, help="OpenCode session ID (ses_...)")
args = parser.parse_args()

STORAGE = Path.home() / ".local/share/opencode/storage"
MSG_DIR = STORAGE / "message" / args.session_id
PART_DIR = STORAGE / "part"

if not MSG_DIR.exists():
    print(
        f"WARNING: Message directory not found for session {args.session_id}",
        file=sys.stderr,
    )
    sys.exit(0)

messages = []
for msg_file in sorted(MSG_DIR.glob("*.json")):
    try:
        msg = json.loads(msg_file.read_text())
    except json.JSONDecodeError as e:
        print(f"WARNING: Skipping malformed message file {msg_file}: {e}", file=sys.stderr)
        continue
    messages.append((msg.get("time", {}).get("created", 0), msg))

for _, msg in sorted(messages, key=lambda x: x[0]):
    msg_id = msg["id"]
    role = msg.get("role", "user")
    part_dir = PART_DIR / msg_id

    if not part_dir.exists():
        continue

    parts = []
    for part_file in part_dir.glob("*.json"):
        try:
            part = json.loads(part_file.read_text())
        except json.JSONDecodeError as e:
            print(
                f"WARNING: Skipping malformed part file {part_file}: {e}",
                file=sys.stderr,
            )
            continue
        parts.append(part)

    if role == "user":
        text = " ".join(p.get("text", "") for p in parts if p.get("type") == "text")
        if text:
            print(json.dumps({"object_type": "ChatInputUserMessage", "text": text}))
    else:
        content = []
        for p in parts:
            if p.get("type") == "text" and p.get("text"):
                content.append({"object_type": "TextBlock", "type": "text", "text": p["text"]})
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
