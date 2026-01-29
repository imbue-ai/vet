import json
from pathlib import Path
from typing import assert_never

from loguru import logger
from pydantic import TypeAdapter
from pydantic import ValidationError

from vet_types.chat_state import ContentBlockTypes
from vet_types.messages import ChatInputUserMessage
from vet_types.messages import ConversationMessageUnion
from vet_types.messages import ResponseBlockAgentMessage

CONVERSATION_FILE_ENV_VAR = "CONVERSATION_FILE"
TASK_SOURCE_BRANCH_ENV_VAR = "TASK_SOURCE_BRANCH"


class ConversationLoadingError(Exception):
    pass


# === formatting for prompt ===


def delete_unnecessary_content_block_fields(block: ContentBlockTypes) -> str:
    """Returns the content as a json-serialized string without the fields that we don't want to include in the prompt"""
    fields_to_remove = {"id"}
    return block.model_dump_json(exclude=fields_to_remove)


def delete_unnecessary_conversation_message_fields(
    message: ConversationMessageUnion,
) -> str:
    """Returns the message as a json-serialized string without the fields that we don't want to include in the prompt"""
    general_fields_to_remove = {"message_id", "source", "approximate_creation_time"}
    match message:
        case ChatInputUserMessage():
            # remove the 'files' field if it's empty
            fields_to_remove = general_fields_to_remove | {"model_name"} | {"files"} if not message.files else set()
            return message.model_dump_json(exclude=fields_to_remove)
        case ResponseBlockAgentMessage():
            fields_to_remove = general_fields_to_remove | {"assistant_message_id"}
            return json.dumps(
                message.model_dump(mode="json", exclude=fields_to_remove)
                | {"content": [delete_unnecessary_content_block_fields(block) for block in message.content]}
            )
        case _ as unreachable:
            assert_never(unreachable)


def format_conversation_history_for_prompt(
    conversation_history: tuple[ConversationMessageUnion, ...],
) -> str:
    formatted_messages = [delete_unnecessary_conversation_message_fields(message) for message in conversation_history]
    return "\n".join(message for message in formatted_messages if message is not None)


# === loading from file ===


def load_conversation_history(
    conversation_file_path: Path,
) -> tuple[ConversationMessageUnion, ...]:
    """Load a jsonl file into a list of conversation messages"""
    file_contents = conversation_file_path.read_text()
    return parse_conversation_history(file_contents)


def parse_conversation_history(
    conversation_str: str,
) -> tuple[ConversationMessageUnion, ...]:
    """Load a jsonl string into a list of conversation messages"""
    messages = []
    for line in conversation_str.strip().splitlines():
        try:
            # deserialize the message with pydantic
            message: ConversationMessageUnion = TypeAdapter(ConversationMessageUnion).validate_json(line)
        except ValidationError:
            logger.info("Skipping malformed history line {}", line)
            continue
        messages.append(message)
    return tuple(messages)
