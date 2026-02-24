#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
import tempfile

parser = argparse.ArgumentParser(description="Export OpenCode session history for vet")
parser.add_argument("--session-id", required=True, help="OpenCode session ID (ses_...)")
args = parser.parse_args()

fd, tmppath = tempfile.mkstemp(suffix=".json")
try:
    with os.fdopen(fd, "w+b") as f:
        try:
            result = subprocess.run(
                ["opencode", "export", args.session_id],
                stdout=f,
                stderr=subprocess.PIPE,
            )
        except (FileNotFoundError, OSError) as e:
            print(
                f"WARNING: Could not run 'opencode' command: {e}",
                file=sys.stderr,
            )
            sys.exit(0)

    if result.returncode != 0:
        print(
            f"WARNING: opencode export failed for session {args.session_id}: {result.stderr.decode().strip()}",
            file=sys.stderr,
        )
        sys.exit(0)

    with open(tmppath, "r") as f:
        raw = f.read()
finally:
    os.unlink(tmppath)

if not raw.strip():
    print(
        f"WARNING: opencode export returned empty output for session {args.session_id}",
        file=sys.stderr,
    )
    sys.exit(0)

try:
    data = json.loads(raw)
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
                content.append({"object_type": "TextBlock", "type": "text", "text": p["text"]})
            elif p.get("type") == "tool":
                call_id = p.get("callID", "")
                tool_name = p.get("tool", "")
                state = p.get("state", {})
                tool_input = state.get("input", {})
                tool_output = state.get("output", "")
                content.append(
                    {
                        "object_type": "ToolUseBlock",
                        "type": "tool_use",
                        "id": call_id,
                        "name": tool_name,
                        "input": tool_input,
                    }
                )
                content.append(
                    {
                        "object_type": "ToolResultBlock",
                        "type": "tool_result",
                        "tool_use_id": call_id,
                        "tool_name": tool_name,
                        "invocation_string": f"{tool_name}({json.dumps(tool_input)})",
                        "content": {"content_type": "generic", "text": tool_output},
                    }
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
