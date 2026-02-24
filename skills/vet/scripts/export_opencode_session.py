#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys

parser = argparse.ArgumentParser(description="Export OpenCode session history for vet")
parser.add_argument("--session-id", required=True, help="OpenCode session ID (ses_...)")
args = parser.parse_args()

result = subprocess.run(
    ["opencode", "export", args.session_id],
    capture_output=True,
    text=True,
)

if result.returncode != 0:
    print(
        f"WARNING: opencode export failed for session {args.session_id}: {result.stderr.strip()}",
        file=sys.stderr,
    )
    sys.exit(0)

if not result.stdout.strip():
    print(
        f"WARNING: opencode export returned empty output for session {args.session_id}",
        file=sys.stderr,
    )
    sys.exit(0)

try:
    data = json.loads(result.stdout)
except json.JSONDecodeError as e:
    print(f"WARNING: Failed to parse opencode export output: {e}", file=sys.stderr)
    sys.exit(0)

for msg in data.get("messages", []):
    info = msg.get("info", {})
    parts = msg.get("parts", [])
    role = info.get("role", "user")
    msg_id = info.get("id", "")

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
