#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

SESSION_FILE = os.environ.get("CODEX_SESSION_FILE")
if not SESSION_FILE:
    sessions_dir = Path.home() / ".codex/sessions"
    if sessions_dir.exists():
        files = list(sessions_dir.rglob("*.jsonl"))
        if files:
            SESSION_FILE = str(max(files, key=lambda f: f.stat().st_mtime))

if not SESSION_FILE or not Path(SESSION_FILE).exists():
    sys.exit(0)

for line in Path(SESSION_FILE).read_text().splitlines():
    if not line.strip():
        continue
    entry = json.loads(line)

    if entry.get("type") != "response_item":
        continue

    payload = entry.get("payload", {})
    if payload.get("type") != "message":
        continue

    role = payload.get("role")
    content = payload.get("content", [])

    if role == "user":
        text = " ".join(
            c.get("text", "") for c in content if c.get("type") == "input_text"
        )
        if text:
            print(json.dumps({"object_type": "ChatInputUserMessage", "text": text}))
    elif role == "assistant":
        blocks = []
        for c in content:
            if c.get("type") == "output_text" and c.get("text"):
                blocks.append({"type": "TextBlock", "text": c["text"]})
        if blocks:
            print(
                json.dumps(
                    {
                        "object_type": "ResponseBlockAgentMessage",
                        "role": "assistant",
                        "assistant_message_id": "codex_msg",
                        "content": blocks,
                    }
                )
            )
