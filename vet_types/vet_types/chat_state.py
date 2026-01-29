"""Chat state types for imbue_verify."""

from typing import Annotated
from typing import Any
from typing import Literal

from pydantic import Field
from pydantic import Tag

from imbue_core.pydantic_serialization import SerializableModel
from imbue_core.pydantic_serialization import build_discriminator
from vet_types.ids import TaskID
from vet_types.ids import ToolUseID


# ========================
# Chat Type Definitions
# ========================


class ContentBlock(SerializableModel):
    object_type: str = Field(..., description="Type discriminator for content blocks")
    type: str = Field(..., description="Type discriminator for content blocks")


class TextBlock(ContentBlock):
    object_type: str = "TextBlock"
    type: Literal["text"] = "text"
    text: str


class ContextSummaryBlock(ContentBlock):
    object_type: str = "ContextSummaryBlock"
    type: Literal["context_summary"] = "context_summary"
    text: str


class ResumeResponseBlock(ContentBlock):
    object_type: str = "ResumeResponseBlock"
    type: Literal["resume_response"] = "resume_response"


class ForkedToBlock(ContentBlock):
    object_type: str = "ForkedToBlock"
    type: Literal["forked_to"] = "forked_to"
    forked_to_task_id: TaskID


class ForkedFromBlock(ContentBlock):
    object_type: str = "ForkedFromBlock"
    type: Literal["forked_from"] = "forked_from"
    forked_from_task_id: TaskID


class CommandBlock(ContentBlock):
    object_type: str = "CommandBlock"
    type: Literal["command"] = "command"
    command: str
    is_automated: bool = Field(default=False, description="Whether the command is automated")


ToolInput = dict[str, Any]


class ToolUseBlock(ContentBlock):
    object_type: str = "ToolUseBlock"
    type: Literal["tool_use"] = "tool_use"
    id: ToolUseID = Field(..., description="Unique identifier for this tool use")
    name: str = Field(..., description="Name of the tool being used")
    input: ToolInput = Field(default_factory=ToolInput, description="Input parameters for the tool")


class ToolResultContent(SerializableModel):
    """Base class for tool result content with type discriminator"""

    content_type: str = Field(..., description="Type discriminator for tool result content")


class SimpleToolContent(ToolResultContent):
    """Generic tool content, or information to reconstruct diff tool content"""

    content_type: Literal["simple"] = "simple"
    text: str = Field(..., description="The tool output as text")
    tool_input: ToolInput
    tool_content: Any


class GenericToolContent(ToolResultContent):
    """Generic content for most tools - just a string"""

    content_type: Literal["generic"] = "generic"
    text: str = Field(..., description="The tool output as text")


class DiffToolContent(ToolResultContent):
    """Content for diff-producing tools (Write, Edit, MultiEdit)"""

    content_type: Literal["diff"] = "diff"
    diff: str = Field(..., description="The git diff string")
    file_path: str = Field(..., description="The file that was modified")


ToolResultContentType = GenericToolContent | DiffToolContent


class ToolResultBlock(ContentBlock):
    object_type: str = "ToolResultBlock"
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: ToolUseID = Field(..., description="ID of the corresponding tool use")
    tool_name: str = Field(..., description="Name of the tool that was used")
    invocation_string: str = Field(..., description="String representation of how the tool was invoked")
    content: ToolResultContentType = Field(..., description="Result content from the tool execution")
    is_error: bool = Field(default=False, description="Whether the tool execution resulted in an error")


class WarningBlock(ContentBlock):
    object_type: str = "WarningBlock"
    type: Literal["warning"] = "warning"
    message: str = Field(..., description="Warning message")
    traceback: str | None = Field(..., description="Warning traceback")
    warning_type: str | None = Field(..., description="Type of warning, i.e. name of the exception that was raised")


class ErrorBlock(ContentBlock):
    object_type: str = "ErrorBlock"
    type: Literal["error"] = "error"
    message: str = Field(..., description="Error message")
    traceback: str = Field(..., description="Error traceback")
    error_type: str = Field(..., description="Type of error, i.e. name of the exception that was raised")


class FileBlock(ContentBlock):
    object_type: str = "FileBlock"
    type: Literal["file"] = "file"
    source: str = Field(..., description="A file path on the users local machine.")


ContentBlockTypes = Annotated[
    (
        Annotated[TextBlock, Tag("TextBlock")]
        | Annotated[CommandBlock, Tag("CommandBlock")]
        | Annotated[ToolUseBlock, Tag("ToolUseBlock")]
        | Annotated[ToolResultBlock, Tag("ToolResultBlock")]
        | Annotated[ErrorBlock, Tag("ErrorBlock")]
        | Annotated[WarningBlock, Tag("WarningBlock")]
        | Annotated[ContextSummaryBlock, Tag("ContextSummaryBlock")]
        | Annotated[ResumeResponseBlock, Tag("ResumeResponseBlock")]
        | Annotated[FileBlock, Tag("FileBlock")]
        | Annotated[ForkedToBlock, Tag("ForkedToBlock")]
        | Annotated[ForkedFromBlock, Tag("ForkedFromBlock")]
    ),
    build_discriminator(),
]
