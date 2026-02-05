#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

parser = argparse.ArgumentParser(description="Export Claude Code session history for vet")
parser.add_argument("--session-file", required=True, help="Path to Claude Code session .jsonl file")
args = parser.parse_args()

SESSION_FILE = Path(args.session_file)
if not SESSION_FILE.exists():
    sys.exit(0)

for line in SESSION_FILE.read_text().splitlines():
    if not line.strip():
        continue
    try:
        entry = json.loads(line)
    except json.JSONDecodeError as e:
        print(
            f"WARNING: Skipping malformed JSON line in {SESSION_FILE}: {e}",
            file=sys.stderr,
        )
        continue

    entry_type = entry.get("type")
    if entry_type not in ("user", "assistant"):
        continue

    if entry.get("isSidechain"):
        continue

    message = entry.get("message", {})
    content = message.get("content")

    if entry_type == "user":
        if isinstance(content, str) and content.strip():
            print(json.dumps({"object_type": "ChatInputUserMessage", "text": content}))
        elif isinstance(content, list):
            text = " ".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
            if text.strip():
                print(json.dumps({"object_type": "ChatInputUserMessage", "text": text}))
    elif entry_type == "assistant":
        if not isinstance(content, list):
            continue
        blocks = []
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text" and c.get("text"):
                blocks.append({"object_type": "TextBlock", "type": "text", "text": c["text"]})
        if blocks:
            print(
                json.dumps(
                    {
                        "object_type": "ResponseBlockAgentMessage",
                        "role": "assistant",
                        "assistant_message_id": message.get("id", entry.get("uuid", "claude_code_msg")),
                        "content": blocks,
                    }
                )
            )
