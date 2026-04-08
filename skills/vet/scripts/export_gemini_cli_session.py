#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

parser = argparse.ArgumentParser(description="Export Gemini CLI session history for vet")
parser.add_argument("--session-file", required=True, help="Path to Gemini CLI session .json file")
args = parser.parse_args()

SESSION_FILE = Path(args.session_file)
if not SESSION_FILE.exists():
    print(f"ERROR: Session file {SESSION_FILE} does not exist", file=sys.stderr)
    sys.exit(1)

try:
    data = json.loads(SESSION_FILE.read_text())
except json.JSONDecodeError as e:
    print(f"ERROR: Failed to parse JSON from {SESSION_FILE}: {e}", file=sys.stderr)
    sys.exit(1)

messages = data.get("messages", [])

for msg in messages:
    msg_type = msg.get("type")
    content = msg.get("content")

    if msg_type == "user":
        if isinstance(content, list):
            text = " ".join(c.get("text", "") for c in content if isinstance(c, dict) and "text" in c)
        else:
            text = str(content)

        if text:
            print(json.dumps({"object_type": "ChatInputUserMessage", "text": text}))

    elif msg_type == "gemini":
        blocks = []

        # Add the text content as a TextBlock if it exists
        if content and isinstance(content, str):
            blocks.append({"object_type": "TextBlock", "type": "text", "text": content})

        # Process tool calls
        tool_calls = msg.get("toolCalls", [])
        for tc in tool_calls:
            call_id = tc.get("id")
            name = tc.get("name")
            tool_args = tc.get("args")

            blocks.append(
                {
                    "object_type": "ToolUseBlock",
                    "type": "tool_use",
                    "id": call_id,
                    "name": name,
                    "input": tool_args,
                }
            )

            # Process tool results
            results = tc.get("result", [])
            for res in results:
                # Results can be complex; extract the response content
                # Based on the example, it's often in functionResponse.response.output
                output = ""
                if "functionResponse" in res:
                    fr = res["functionResponse"]
                    response = fr.get("response", {})
                    if isinstance(response, dict):
                        output = response.get("output", "")
                    else:
                        output = str(response)
                else:
                    output = str(res)

                blocks.append(
                    {
                        "object_type": "ToolResultBlock",
                        "type": "tool_result",
                        "tool_use_id": call_id,
                        "tool_name": name,
                        "invocation_string": f"{name}({json.dumps(tool_args)})",
                        "content": {"content_type": "generic", "text": str(output)},
                    }
                )

        if blocks:
            print(
                json.dumps(
                    {
                        "object_type": "ResponseBlockAgentMessage",
                        "role": "assistant",
                        "assistant_message_id": msg.get("id"),
                        "content": blocks,
                    }
                )
            )

    elif msg_type == "info":
        # Info messages are usually system notifications, maybe skip or map to something else?
        # For now, let's just skip them as they don't typically represent agent-user dialogue.
        pass
