from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from openai import NOT_GIVEN
from openai.types.chat import ChatCompletion
from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_message import ChatCompletionMessage

from vet.imbue_core.agents.llm_apis.data_types import LanguageModelGenerationParams
from vet.imbue_core.agents.llm_apis.openai_api import OpenAIChatAPI
from vet.imbue_core.agents.llm_apis.openai_api import OpenAIModelName
from vet.imbue_core.agents.llm_apis.openai_api import _accepts_logprobs_parameter


def _make_completion(content: str) -> ChatCompletion:
    return ChatCompletion(
        id="chatcmpl-test",
        choices=[
            Choice(
                index=0,
                finish_reason="stop",
                message=ChatCompletionMessage(role="assistant", content=content),
            )
        ],
        created=0,
        model="test-model",
        object="chat.completion",
    )


def test_astra_does_not_accept_logprobs_parameter() -> None:
    assert not _accepts_logprobs_parameter(OpenAIModelName.GPT_6_ASTRA)
    assert _accepts_logprobs_parameter(OpenAIModelName.GPT_5_6_SOL)


@pytest.mark.anyio
async def test_astra_omits_unsupported_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    create = AsyncMock(return_value=_make_completion("OK"))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(OpenAIChatAPI, "_get_client", lambda self: client)
    api = OpenAIChatAPI(model_name=OpenAIModelName.GPT_6_ASTRA, cache_path=None)

    await api._call_api("[ROLE=USER]\nReply OK", LanguageModelGenerationParams(max_tokens=16))

    assert create.await_args.kwargs["temperature"] is NOT_GIVEN
    assert create.await_args.kwargs["logprobs"] is NOT_GIVEN
    assert create.await_args.kwargs["top_logprobs"] is NOT_GIVEN
