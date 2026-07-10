#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

parser = argparse.ArgumentParser(description="Export Kiro CLI session history for vet")
group = parser.add_mutually_exclusive_group(required=True)
group.add_argument("--session-id", help="Kiro CLI session UUID")
group.add_argument("--session-file", help="Path to Kiro CLI session .jsonl file")
args = parser.parse_args()

if args.session_file:
    SESSION_FILE = Path(args.session_file)
else:
    SESSION_FILE = Path.home() / ".kiro" / "sessions" / "cli" / f"{args.session_id}.jsonl"

if not SESSION_FILE.exists():
    print(f"WARNING: Kiro session file not found: {SESSION_FILE}", file=sys.stderr)
    sys.exit(0)

# Map toolUseId -> (tool_name, tool_input) so ToolResultBlocks can reference the tool name
call_info: dict[str, tuple[str, dict]] = {}
# Buffer tool blocks so they can be wrapped in a ResponseBlockAgentMessage
tool_block_buffer: list[dict] = []
msg_counter = 0


def flush_tool_blocks() -> None:
    """Emit any buffered tool blocks wrapped in a ResponseBlockAgentMessage."""
    global msg_counter
    if not tool_block_buffer:
        return
    msg_counter += 1
    print(
        json.dumps(
            {
                "object_type": "ResponseBlockAgentMessage",
                "role": "assistant",
                "assistant_message_id": f"kiro_tool_msg_{msg_counter}",
                "content": list(tool_block_buffer),
            }
        )
    )
    tool_block_buffer.clear()


def tool_result_text(content_items: list) -> str:
    parts = []
    for item in content_items:
        if item.get("kind") == "text":
            parts.append(item.get("data", ""))
        elif item.get("kind") == "json":
            parts.append(json.dumps(item.get("data")))
    return "\n".join(parts)


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

    kind = entry.get("kind")
    data = entry.get("data", {})
    content = data.get("content", [])

    if kind == "Prompt":
        flush_tool_blocks()
        text = " ".join(c.get("data", "") for c in content if c.get("kind") == "text")
        if text:
            print(json.dumps({"object_type": "ChatInputUserMessage", "text": text}))
        continue

    if kind == "AssistantMessage":
        blocks = list(tool_block_buffer)
        tool_block_buffer.clear()
        for c in content:
            if c.get("kind") == "text" and c.get("data"):
                blocks.append({"object_type": "TextBlock", "type": "text", "text": c["data"]})
            elif c.get("kind") == "toolUse":
                tu = c.get("data", {})
                tool_use_id = tu.get("toolUseId", "")
                tool_name = tu.get("name", "")
                tool_input = tu.get("input", {})
                call_info[tool_use_id] = (tool_name, tool_input)
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
            msg_counter += 1
            print(
                json.dumps(
                    {
                        "object_type": "ResponseBlockAgentMessage",
                        "role": "assistant",
                        "assistant_message_id": data.get("message_id", f"kiro_msg_{msg_counter}"),
                        "content": blocks,
                    }
                )
            )
        continue

    if kind == "ToolResults":
        for c in content:
            if c.get("kind") != "toolResult":
                continue
            tr = c.get("data", {})
            tool_use_id = tr.get("toolUseId", "")
            tool_name, tool_input = call_info.get(tool_use_id, ("unknown", {}))
            tool_block_buffer.append(
                {
                    "object_type": "ToolResultBlock",
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "tool_name": tool_name,
                    "invocation_string": f"{tool_name}({json.dumps(tool_input)})",
                    "content": {
                        "content_type": "generic",
                        "text": tool_result_text(tr.get("content", [])),
                    },
                }
            )
        continue

    # OtelSpan and any other/unknown kind: skip

# Flush any remaining tool blocks at end of file
flush_tool_blocks()
