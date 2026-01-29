import json
import re
from abc import ABC
from typing import Any
from typing import Sequence
from typing import cast

from loguru import logger

from imbue_core.agents.agent_api.data_types import AgentToolName
from imbue_core.async_monkey_patches import log_exception
from imbue_core.ids import AssistantMessageID
from imbue_core.imbue_cli.action import ActionOutput
from imbue_core.pydantic_serialization import SerializableModel
from imbue_core.pydantic_serialization import model_load
from imbue_core.sculptor.state.chat_state import ContentBlockTypes
from imbue_core.sculptor.state.chat_state import ImbueCLIToolContent
from imbue_core.sculptor.state.chat_state import SimpleToolContent
from imbue_core.sculptor.state.chat_state import TextBlock
from imbue_core.sculptor.state.chat_state import ToolInput
from imbue_core.sculptor.state.chat_state import ToolResultBlock
from imbue_core.sculptor.state.chat_state import ToolResultBlockSimple
from imbue_core.sculptor.state.chat_state import ToolUseBlock
from imbue_core.sculptor.state.mcp_constants import IMBUE_CLI_MCP_TOOL_PREFIXES
from imbue_core.sculptor.telemetry import PosthogEventPayload
from imbue_core.sculptor.telemetry_constants import ConsentLevel
from imbue_core.sculptor.telemetry_utils import never_log
from imbue_core.sculptor.telemetry_utils import with_consent
from imbue_core.sculptor.telemetry_utils import without_consent

RE_STRIP_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[mGKHfABCDhls]|\x1b\[[?][0-9;]*[hlHLdcE]|\x1b[=>]")


# ===========================================
# Parsed Agent Message Type Definitions
# ===========================================


class ParsedStreamEvent(SerializableModel, ABC):
    pass


class MessageStartEvent(ParsedStreamEvent):
    """Emitted when a new assistant message begins streaming."""

    event_type: str = "message_start"
    message_id: str


class MessageStopEvent(ParsedStreamEvent):
    """Emitted when the assistant message is complete."""

    event_type: str = "message_stop"


class ContentBlockStartEvent(ParsedStreamEvent):
    """Emitted when a new content block (text or tool_use) begins."""

    event_type: str = "content_block_start"
    block_type: str
    index: int


class ToolBlockStartEvent(ContentBlockStartEvent):
    block_type: str = "tool_start"
    tool_id: str
    tool_name: str


class TextBlockStartEvent(ContentBlockStartEvent):
    block_type: str = "text_start"


class ContentBlockDeltaEvent(ParsedStreamEvent, ABC):
    """Base class for incremental content updates within a block."""

    event_type: str = "content_block_delta"
    index: int


class TextDeltaEvent(ContentBlockDeltaEvent):
    """Emitted for incremental text content updates."""

    delta_type: str = "text_delta"
    text: str


class ToolInputDeltaEvent(ContentBlockDeltaEvent):
    """Emitted for incremental tool input JSON updates."""

    delta_type: str = "input_json_delta"
    partial_json: str


class ContentBlockStopEvent(ParsedStreamEvent):
    """Emitted when a content block is complete."""

    event_type: str = "content_block_stop"
    index: int


ParsedStreamEventTypes = (
    MessageStartEvent
    | MessageStopEvent
    | ContentBlockStartEvent
    | ToolBlockStartEvent
    | TextBlockStartEvent
    | TextDeltaEvent
    | ToolInputDeltaEvent
    | ContentBlockStopEvent
)


class ParsedAgentResponse(PosthogEventPayload):
    """Base class for parsed agent messages with type discriminator"""

    object_type: str = without_consent(description="Type discriminator for parsed messages")


class ParsedInitResponse(ParsedAgentResponse):
    object_type: str = without_consent(default="ParsedInitResponse")
    session_id: str = with_consent(ConsentLevel.LLM_LOGS, description="Session ID from claude code init")
    # TODO: make the status richer or represent the server as its own object type
    mcp_servers: dict[str, str] = never_log(description="Map from enabled MCP servers to their statuses")
    tools: list[str] = with_consent(ConsentLevel.LLM_LOGS, default=[], description="List of all available tools")


class ParsedAssistantResponse(ParsedAgentResponse):
    object_type: str = without_consent(default="ParsedAssistantResponse")
    message_id: AssistantMessageID = without_consent(description="Unique identifier for assistant message")
    content_blocks: list[ContentBlockTypes] = with_consent(
        ConsentLevel.LLM_LOGS, description="Content blocks containing assistant response data"
    )


class ParsedUserResponse(ParsedAgentResponse):
    object_type: str = without_consent(default="ParsedUserResponse")
    content_blocks: list[ContentBlockTypes] = with_consent(
        ConsentLevel.LLM_LOGS,
        description="Content blocks containing user response data",
    )


class ParsedToolResultResponseSimple(ParsedAgentResponse):
    object_type: str = without_consent(default="ParsedToolResultResponse")
    content_blocks: Sequence[ToolResultBlockSimple] = with_consent(
        ConsentLevel.LLM_LOGS, description="Tool result content blocks that may contain user data"
    )


ParsedUserResponseTypeSimple = ParsedUserResponse | ParsedToolResultResponseSimple


class ParsedToolResultResponse(ParsedAgentResponse):
    object_type: str = without_consent(default="ParsedToolResultResponse")
    content_blocks: Sequence[ToolResultBlock] = with_consent(
        ConsentLevel.LLM_LOGS, description="Tool result content blocks that may contain user data"
    )


class ParsedEndResponse(ParsedAgentResponse):
    object_type: str = without_consent(default="ParsedEndResponse")
    is_error: bool = without_consent(default=False, description="Whether the stream ended due to an error")
    result: str = with_consent(ConsentLevel.LLM_LOGS, description="The result of the stream")
    status: str | None = with_consent(
        ConsentLevel.PRODUCT_ANALYTICS, default=None, description="Optional status field for result"
    )
    duration_ms: float | None = with_consent(
        ConsentLevel.PRODUCT_ANALYTICS, description="Wallclock duration of agent process"
    )
    duration_api_ms: float | None = with_consent(
        ConsentLevel.PRODUCT_ANALYTICS, description="Model compute duration of agent process if provided"
    )
    num_turns: int | None = with_consent(
        ConsentLevel.PRODUCT_ANALYTICS, description="Number of turns in this agent session"
    )
    # Session ID can be the claude_code session ID which potentially exposes user messages
    session_id: str | None = with_consent(ConsentLevel.LLM_LOGS, description="Agent call session ID")
    total_tokens: int | None = with_consent(ConsentLevel.PRODUCT_ANALYTICS, description="Total number of tokens")
    input_tokens: int | None = with_consent(ConsentLevel.PRODUCT_ANALYTICS, description="Input tokens")
    output_tokens: int | None = with_consent(ConsentLevel.PRODUCT_ANALYTICS, description="Output tokens")
    total_cost_usd: float | None = with_consent(
        ConsentLevel.PRODUCT_ANALYTICS, description="Total cost of agent session"
    )


class ParsedCompactionSummaryResponse(ParsedAgentResponse):
    object_type: str = without_consent(default="ParsedCompactionSummaryResponse")
    content: TextBlock = with_consent(
        ConsentLevel.LLM_LOGS,
        description="Content blocks containing user response data",
    )


# the tool results are not parsed in this kind of message
ParsedAgentResponseTypeSimple = (
    ParsedInitResponse
    | ParsedAssistantResponse
    | ParsedUserResponseTypeSimple
    | ParsedEndResponse
    | ParsedCompactionSummaryResponse
)


# ===========================================
# Parsing claude code json files
# ===========================================


def get_tool_invocation_string(tool_name: str, tool_input: ToolInput, _tool_result: str | None = None) -> str:
    """Generate a human-readable invocation string for a tool."""
    if tool_name == AgentToolName.READ:
        result = tool_input.get("file_path", "")
    elif tool_name in [AgentToolName.WRITE, AgentToolName.EDIT, AgentToolName.MULTI_EDIT]:
        result = tool_input.get("file_path", "")
    elif tool_name == AgentToolName.BASH:
        result = tool_input.get("command", "")
    elif tool_name in [AgentToolName.GREP, AgentToolName.GLOB]:
        pattern = tool_input.get("pattern", "")
        path = tool_input.get("path", "")
        result = f'"{pattern}"' + (f" in {path}" if path else "")
    elif tool_name == AgentToolName.LS:
        result = tool_input.get("path", "")
    elif tool_name == AgentToolName.NOTEBOOK_READ:
        result = tool_input.get("notebook_path", "")
    elif tool_name == AgentToolName.NOTEBOOK_EDIT:
        result = tool_input.get("notebook_path", "")
    elif tool_name == AgentToolName.WEB_FETCH:
        result = tool_input.get("url", "")
    elif tool_name == AgentToolName.TODO_READ:
        result = "read todos"
    elif tool_name == AgentToolName.TODO_WRITE:
        todos: list[str] = tool_input.get("todos", [])
        result = f"update {len(todos)} todos"
    elif tool_name == AgentToolName.WEB_SEARCH:
        result = tool_input.get("query", "")
    elif tool_name == AgentToolName.TASK:
        result = tool_input.get("description", "")
    else:
        # For unknown tools, try to extract the most relevant field
        if "path" in tool_input:
            result = tool_input["path"]
        elif "file_path" in tool_input:
            result = tool_input["file_path"]
        elif "command" in tool_input:
            result = tool_input["command"]
        else:
            # Return first non-empty string value
            for value in tool_input.values():
                if isinstance(value, str) and value:
                    result = value
            result = "tool invocation"
    return cast(str, result)  # for the type checker


def is_tool_name_in_servers(tool_name: str) -> bool:
    return any(tool_name.startswith(f"{mcp_prefix}__") for mcp_prefix in IMBUE_CLI_MCP_TOOL_PREFIXES)


def parse_imbue_cli_content(tool_result: dict[str, Any]) -> tuple[ImbueCLIToolContent, str]:
    """Parse Imbue CLI tool result into structured content and a single summary line to show to the user."""
    action_outputs: list[ActionOutput] = []
    try:
        action_output_dicts = json.loads(tool_result["text"])
        for action_output_dict in action_output_dicts:
            try:
                action_output = model_load(ActionOutput, action_output_dict)
            except Exception as e:
                log_exception(
                    e, "Failed to parse action output {action_output_dict}", action_output_dict=action_output_dict
                )
                continue
            action_outputs.append(action_output)
    except Exception as e:
        log_exception(e, "Failed to parse imbue cli tool result {tool_result}", tool_result=tool_result)
        return (ImbueCLIToolContent(action_outputs=[]), "Failed to parse the tool results")

    output_count = sum(len(action_output.outputs) for action_output in action_outputs)
    if len(action_outputs) == 1:
        summary_prefix = f"Imbue CLI action '{action_outputs[0].command}' found"
    else:
        summary_prefix = f"Executed {len(action_outputs)} Imbue CLI actions and received {output_count} outputs"

    return (ImbueCLIToolContent(action_outputs=action_outputs), summary_prefix)


def _handle_init_message(data: dict[str, Any]) -> ParsedInitResponse:
    """Handle system/init message type."""
    mcp_servers = data.get("mcp_servers", [])
    tools = data.get("tools", [])

    if mcp_servers:
        logger.debug("MCP servers found in init message: {}", mcp_servers)

    return ParsedInitResponse(
        session_id=data["session_id"],
        mcp_servers={server["name"]: server["status"] for server in mcp_servers},
        tools=tools,
    )


def _handle_assistant_message(data: dict[str, Any]) -> ParsedAssistantResponse:
    """Handle assistant message type."""
    message_data = data["message"]
    message_id = message_data["id"]

    content_blocks: list[ContentBlockTypes] = []
    for content in message_data["content"]:
        if content["type"] == "text":
            content_blocks.append(TextBlock(text=content["text"]))
        elif content["type"] == "tool_use":
            content_blocks.append(ToolUseBlock(id=content["id"], name=content["name"], input=content["input"]))

    return ParsedAssistantResponse(message_id=message_id, content_blocks=content_blocks)


def _handle_tool_result_message(
    data: dict[str, Any],
    tool_use_map: dict[str, tuple[str, ToolInput]] | None,
) -> ParsedUserResponseTypeSimple | None:
    """Handle user/tool result message type without parsing tool content."""

    message_content = data["message"]["content"]

    if isinstance(message_content, str):
        return ParsedUserResponse(content_blocks=[TextBlock(text=message_content)])
    elif message_content[0]["type"] == "text":
        if len(message_content) > 1:
            logger.warning("Message content has more than one block: {}", message_content)
        return ParsedUserResponse(content_blocks=[TextBlock(text=message_content[0]["text"])])
    elif message_content[0]["type"] == "document":
        if len(message_content) > 1:
            logger.warning("Message content has more than one block: {}", message_content)
        media_type = message_content[0].get("source", {}).get("media_type", "UNSPECIFIED")
        return ParsedUserResponse(content_blocks=[TextBlock(text=f"Document, media_type: {media_type}")])

    tool_result = message_content[0]
    tool_use_id = tool_result["tool_use_id"]

    # Get tool info from map
    tool_name, tool_input = (
        tool_use_map.get(tool_use_id, ("unknown", ToolInput())) if tool_use_map else ("unknown", ToolInput())
    )

    tool_result_content = tool_result["content"]
    tool_content: ImbueCLIToolContent | SimpleToolContent
    if is_tool_name_in_servers(tool_name):
        if isinstance(tool_result_content, str):
            # TODO: this should be removed once we figure out what is passing a string here
            # (context: https://imbue-ai.slack.com/archives/C06RXB6LY3E/p1758938144717579)
            logger.error("Tool result content is a string: {}", tool_result_content)
            invocation_string = get_tool_invocation_string(tool_name, tool_input, tool_result_content)
            tool_content = SimpleToolContent(
                text=str(tool_result_content), tool_input=tool_input, tool_content=tool_result_content
            )
        else:
            tool_content, invocation_string = parse_imbue_cli_content(tool_result_content[0])
    else:
        invocation_string = get_tool_invocation_string(tool_name, tool_input, tool_result_content)
        tool_content = SimpleToolContent(
            text=str(tool_result_content), tool_input=tool_input, tool_content=tool_result_content
        )

    return ParsedToolResultResponseSimple(
        content_blocks=[
            ToolResultBlockSimple(
                tool_use_id=tool_use_id,
                tool_name=tool_name,
                invocation_string=invocation_string,
                content=tool_content,
                is_error=tool_result.get("is_error", False),
            )
        ]
    )


def _handle_stream_end_message(data: dict[str, Any]) -> ParsedEndResponse:
    """Handle result/stream end message type."""
    return ParsedEndResponse(
        is_error=data.get("is_error", False),
        result=data.get("result", ""),
        status=data.get("subtype", ""),
        duration_ms=data.get("duration_ms", 0),
        duration_api_ms=data.get("duration_api_ms", 0),
        num_turns=data.get("num_turns", 0),
        session_id=data.get("session_id", ""),
        total_tokens=(data.get("usage", {}).get("input_tokens", 0) + data.get("usage", {}).get("output_tokens", 0))
        + data.get("usage", {}).get("cache_creation_input_tokens", 0)
        + data.get("usage", {}).get("cache_read_input_tokens", 0),
        input_tokens=data.get("usage", {}).get("input_tokens", 0),
        output_tokens=data.get("usage", {}).get("output_tokens", 0),
        total_cost_usd=data.get("total_cost_usd", 0),
    )


def parse_claude_code_json_lines_simple(
    line: str,
    tool_use_map: dict[str, tuple[str, ToolInput]] | None = None,
) -> tuple[str, ParsedAgentResponseTypeSimple | None] | None:
    """Parse a JSON line from Claude Code SDK.

    Returns a ParsedAgentMessage subtype or None for unknown message types.
    For tool results, only ever returns GenericToolContent, never DiffToolContent,
    since DiffToolContent requires the diff tracker to be passed in.
    """
    line = RE_STRIP_ANSI_ESCAPE.sub("", line).strip()

    if line == "":
        return None

    data = json.loads(line)

    message_type = data.get("type")

    if message_type == "system" and data.get("subtype") == "init":
        return (message_type, _handle_init_message(data))
    elif message_type == "assistant":
        return (message_type, _handle_assistant_message(data))
    elif message_type == "user":
        # TODO: move tool_use_map out into _load_content_for_tool_result_message
        return (message_type, _handle_tool_result_message(data, tool_use_map))
    elif message_type == "result":
        return (message_type, _handle_stream_end_message(data))

    logger.debug("Unhandled message type: {} with subtype: {}", message_type, data.get("subtype"))

    return None
