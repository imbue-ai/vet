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

# Map tool_use_id -> (tool_name, tool_input) so ToolResultBlocks can reference the tool name
tool_use_info: dict[str, tuple[str, dict]] = {}
msg_counter = 0

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
            text_parts = []
            tool_result_blocks = []
            for c in content:
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "text" and c.get("text"):
                    text_parts.append(c["text"])
                elif c.get("type") == "tool_result":
                    result_content = c.get("content", "")
                    if isinstance(result_content, list):
                        result_content = " ".join(
                            rc.get("text", "")
                            for rc in result_content
                            if isinstance(rc, dict) and rc.get("type") == "text"
                        )
                    tool_use_id = c.get("tool_use_id", "")
                    tool_name, tool_input = tool_use_info.get(tool_use_id, ("unknown", {}))
                    tool_result_blocks.append(
                        {
                            "object_type": "ToolResultBlock",
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "tool_name": tool_name,
                            "invocation_string": f"{tool_name}({json.dumps(tool_input)})",
                            "content": {
                                "content_type": "generic",
                                "text": result_content,
                            },
                        }
                    )
            text = " ".join(text_parts)
            if text.strip():
                print(json.dumps({"object_type": "ChatInputUserMessage", "text": text}))
            if tool_result_blocks:
                msg_counter += 1
                print(
                    json.dumps(
                        {
                            "object_type": "ResponseBlockAgentMessage",
                            "role": "user",
                            "assistant_message_id": f"claude_code_tool_result_{msg_counter}",
                            "content": tool_result_blocks,
                        }
                    )
                )
    elif entry_type == "assistant":
        if not isinstance(content, list):
            continue
        blocks = []
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "text" and c.get("text"):
                blocks.append({"object_type": "TextBlock", "type": "text", "text": c["text"]})
            elif c.get("type") == "tool_use":
                tool_use_id = c.get("id", "")
                tool_name = c.get("name", "")
                tool_input = c.get("input", {})
                # Record for later ToolResultBlock lookups
                tool_use_info[tool_use_id] = (tool_name, tool_input)
                blocks.append(
                    {
                        "object_type": "ToolUseBlock",
                        "type": "tool_use",
                        "id": tool_use_id,
                        "name": tool_name,
                        "input": tool_input,
                    }
                )
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
