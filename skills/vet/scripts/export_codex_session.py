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

# Map call_id -> (fn_name, fn_input) so ToolResultBlocks can reference the tool name
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
                "assistant_message_id": f"codex_tool_msg_{msg_counter}",
                "content": list(tool_block_buffer),
            }
        )
    )
    tool_block_buffer.clear()


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
        call_info[call_id] = (fn_name, fn_input)
        tool_block_buffer.append(
            {
                "object_type": "ToolUseBlock",
                "type": "tool_use",
                "id": call_id,
                "name": fn_name,
                "input": fn_input,
            }
        )
        continue

    if payload_type == "function_call_output":
        call_id = payload.get("call_id", "")
        output = payload.get("output", "")
        fn_name, fn_input = call_info.get(call_id, ("unknown", {}))
        tool_block_buffer.append(
            {
                "object_type": "ToolResultBlock",
                "type": "tool_result",
                "tool_use_id": call_id,
                "tool_name": fn_name,
                "invocation_string": f"{fn_name}({json.dumps(fn_input)})",
                "content": {"content_type": "generic", "text": output},
            }
        )
        continue

    if payload_type != "message":
        continue

    role = payload.get("role")
    content = payload.get("content", [])

    if role == "user":
        # Flush any pending tool blocks before the user message
        flush_tool_blocks()
        text = " ".join(c.get("text", "") for c in content if c.get("type") == "input_text")
        if text:
            print(json.dumps({"object_type": "ChatInputUserMessage", "text": text}))
    elif role == "assistant":
        # Merge buffered tool blocks into this assistant message
        blocks = list(tool_block_buffer)
        tool_block_buffer.clear()
        for c in content:
            if c.get("type") == "output_text" and c.get("text"):
                blocks.append({"object_type": "TextBlock", "type": "text", "text": c["text"]})
        if blocks:
            msg_counter += 1
            print(
                json.dumps(
                    {
                        "object_type": "ResponseBlockAgentMessage",
                        "role": "assistant",
                        "assistant_message_id": f"codex_msg_{msg_counter}",
                        "content": blocks,
                    }
                )
            )

# Flush any remaining tool blocks at end of file
flush_tool_blocks()
