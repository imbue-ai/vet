from typing import Final
from typing import Iterable

from loguru import logger

from vet.imbue_core.agents.llm_apis.data_types import CachingInfo
from vet.imbue_core.agents.llm_apis.data_types import ConversationMessage
from vet.imbue_core.agents.llm_apis.data_types import CostedLanguageModelResponse
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelResponse
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelResponseUsage
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelResponseWithThoughts
from vet.imbue_core.agents.llm_apis.data_types import ResponseStopReason
from vet.imbue_core.agents.llm_apis.data_types import ThoughtResponse
from vet.imbue_core.frozen_utils import FrozenDict
from vet.imbue_core.frozen_utils import FrozenMapping

_ROLE_TO_OPENAI_ROLE: Final[FrozenMapping] = FrozenDict(
    {
        "HUMAN": "user",
        "ASSISTANT": "assistant",
        "SYSTEM": "system",
        "USER": "user",
        "SYSTEM_CACHED": "system",
        "USER_CACHED": "user",
    }
)


def convert_prompt_to_messages(prompt: str, is_cache_role_preserved: bool = False) -> tuple[ConversationMessage, ...]:
    messages = []
    for raw_message in convert_prompt_to_openai_messages(prompt, is_cache_role_preserved):
        messages.append(ConversationMessage(role=raw_message["role"].upper(), content=raw_message["content"]))
    return tuple(messages)


def convert_messages_to_prompt_template(messages: Iterable[ConversationMessage]) -> str:
    return "\n".join(f"[ROLE={message.role.upper()}]\n{message.content}" for message in messages)


def create_costed_language_model_response_for_single_result(
    text: str,
    prompt_tokens: int,
    completion_tokens: int,
    stop_reason: ResponseStopReason,
    network_failure_count: int,
    dollars_used: float,
    thoughts: ThoughtResponse | None = None,
    caching_info: CachingInfo | None = None,
) -> CostedLanguageModelResponse:
    logger.trace("dollars used: {}", dollars_used)
    logger.trace("completion_tokens_used used: {}", completion_tokens)
    if thoughts is None:
        result = LanguageModelResponse(
            text=text,
            token_count=completion_tokens + prompt_tokens,
            stop_reason=stop_reason,
            network_failure_count=network_failure_count,
        )
    else:
        result = LanguageModelResponseWithThoughts(
            text=text,
            token_count=completion_tokens + prompt_tokens,
            stop_reason=stop_reason,
            network_failure_count=network_failure_count,
            thoughts=thoughts,
        )

    return CostedLanguageModelResponse(
        usage=LanguageModelResponseUsage(
            prompt_tokens_used=prompt_tokens,
            completion_tokens_used=completion_tokens,
            dollars_used=dollars_used,
            caching_info=caching_info,
        ),
        responses=(result,),
    )


# FIXME: we should make sure that all our LLM providers use the same function here, some clean up is required
def convert_prompt_to_openai_messages(prompt: str, is_cache_role_preserved: bool = False) -> list[dict[str, str]]:
    prompt = prompt.lstrip()
    assert prompt.startswith("[ROLE=")
    prompt = prompt.replace("[ROLE=", "", 1)
    chunks = prompt.split("\n[ROLE=")
    messages: list[dict[str, str]] = []
    for chunk in chunks:
        lines = chunk.split("\n")
        role = lines[0].strip().rstrip("]")
        assert role in (
            "HUMAN",
            "ASSISTANT",
            "USER",
            "SYSTEM",
            "SYSTEM_CACHED",
            "USER_CACHED",
        ), f"Unknown role {role} in prompt {prompt}"
        lines.pop(0)
        if role == "HUMAN":
            role = "USER"
        if len(messages) > 0:
            messages[-1]["content"] = messages[-1]["content"] + "\n"
        content = "\n".join(lines)
        content = content.rstrip()
        fixed_role = _ROLE_TO_OPENAI_ROLE[role]
        if is_cache_role_preserved and role == "SYSTEM_CACHED":
            fixed_role = "SYSTEM_CACHED"
        elif is_cache_role_preserved and role == "USER_CACHED":
            fixed_role = "USER_CACHED"
        messages.append({"role": fixed_role, "content": content})
    return messages
