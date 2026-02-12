import json
from typing import Callable
from typing import assert_never

from loguru import logger
from pydantic import TypeAdapter
from pydantic import ValidationError

from vet.truncation import truncate_to_token_limit
from vet.vet_types.chat_state import ContentBlockTypes
from vet.vet_types.messages import ChatInputUserMessage
from vet.vet_types.messages import ConversationMessageUnion
from vet.vet_types.messages import ResponseBlockAgentMessage


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
    max_tokens: int | None = None,
    count_tokens: Callable[[str], int] | None = None,
) -> tuple[str, bool]:
    formatted_messages = [delete_unnecessary_conversation_message_fields(message) for message in conversation_history]
    result = "\n".join(message for message in formatted_messages if message is not None)

    if max_tokens is not None and count_tokens is not None:

        result, was_truncated = truncate_to_token_limit(
            result,
            max_tokens=max_tokens,
            count_tokens=count_tokens,
            label="conversation history",
            truncate_end=False,
        )
        return result, was_truncated

    return result, False


# === loading from file ===


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
