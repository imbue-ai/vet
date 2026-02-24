#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

parser = argparse.ArgumentParser(description="Export Codex session history for vet")
parser.add_argument("--session-file", required=True, help="Path to Codex session .jsonl file")
args = parser.parse_args()

SESSION_FILE = args.session_file
if not Path(SESSION_FILE).exists():
    sys.exit(0)

for line in Path(SESSION_FILE).read_text().splitlines():
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

    if entry.get("type") != "response_item":
        continue

    payload = entry.get("payload", {})
    payload_type = payload.get("type")

    if payload_type == "function_call":
        call_id = payload.get("call_id", payload.get("id", ""))
        fn_name = payload.get("name", "")
        fn_args = payload.get("arguments", "")
        # arguments is a JSON string in the Responses API; try to parse it
        try:
            fn_input = json.loads(fn_args) if isinstance(fn_args, str) else fn_args
        except (json.JSONDecodeError, TypeError):
            fn_input = {"raw": fn_args}
        print(
            json.dumps(
                {
                    "object_type": "ToolUseBlock",
                    "type": "tool_use",
                    "id": call_id,
                    "name": fn_name,
                    "input": fn_input,
                }
            )
        )
        continue

    if payload_type == "function_call_output":
        call_id = payload.get("call_id", "")
        output = payload.get("output", "")
        print(
            json.dumps(
                {
                    "object_type": "ToolResultBlock",
                    "type": "tool_result",
                    "tool_use_id": call_id,
                    "content": output,
                }
            )
        )
        continue

    if payload_type != "message":
        continue

    role = payload.get("role")
    content = payload.get("content", [])

    if role == "user":
        text = " ".join(c.get("text", "") for c in content if c.get("type") == "input_text")
        if text:
            print(json.dumps({"object_type": "ChatInputUserMessage", "text": text}))
    elif role == "assistant":
        blocks = []
        for c in content:
            if c.get("type") == "output_text" and c.get("text"):
                blocks.append({"object_type": "TextBlock", "type": "text", "text": c["text"]})
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
