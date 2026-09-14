from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from openai import NOT_GIVEN
from openai.types.chat import ChatCompletion
from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_message import ChatCompletionMessage

from vet.imbue_core.agents.llm_apis import openai_api as openai_api_module
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelGenerationParams
from vet.imbue_core.agents.llm_apis.openai_api import OpenAIChatAPI
from vet.imbue_core.agents.llm_apis.openai_api import OpenAIModelName


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


class _FakeAsyncStream:
    def __aiter__(self):
        async def _events():
            yield SimpleNamespace(
                usage=None,
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content="OK"),
                        finish_reason="stop",
                    )
                ],
            )

        return _events()


@pytest.mark.parametrize(
    "model_name",
    [
        OpenAIModelName.GPT_5_4,
        OpenAIModelName.GPT_5_6,
        OpenAIModelName.GPT_5_6_SOL,
        OpenAIModelName.GPT_5_6_TERRA,
        OpenAIModelName.GPT_5_6_LUNA,
        OpenAIModelName.GPT_6_ASTRA,
    ],
)
@pytest.mark.anyio
async def test_reasoning_models_omit_sampling_parameters(
    model_name: OpenAIModelName, monkeypatch: pytest.MonkeyPatch
) -> None:
    create = AsyncMock(return_value=_make_completion("OK"))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(OpenAIChatAPI, "_get_client", lambda self: client)
    api = OpenAIChatAPI(model_name=model_name, cache_path=None)

    await api._call_api("[ROLE=USER]\nReply OK", LanguageModelGenerationParams(max_tokens=16))

    assert create.await_args.kwargs["temperature"] is NOT_GIVEN
    assert create.await_args.kwargs["logprobs"] is NOT_GIVEN
    assert create.await_args.kwargs["top_logprobs"] is NOT_GIVEN

    create.return_value = _FakeAsyncStream()
    monkeypatch.setattr(openai_api_module, "AsyncStream", _FakeAsyncStream)
    events = [
        event
        async for event in api._get_api_stream(
            "[ROLE=USER]\nReply OK",
            LanguageModelGenerationParams(max_tokens=16),
        )
    ]

    assert events
    assert create.await_args.kwargs["temperature"] is NOT_GIVEN
    assert create.await_args.kwargs["logprobs"] is NOT_GIVEN
    assert create.await_args.kwargs["top_logprobs"] is NOT_GIVEN


@pytest.mark.anyio
async def test_non_reasoning_model_keeps_sampling_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    create = AsyncMock(return_value=_make_completion("OK"))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(OpenAIChatAPI, "_get_client", lambda self: client)
    api = OpenAIChatAPI(model_name=OpenAIModelName.GPT_4_1, cache_path=None)

    await api._call_api("[ROLE=USER]\nReply OK", LanguageModelGenerationParams(max_tokens=16))

    assert create.await_args.kwargs["temperature"] == 0.2
    assert create.await_args.kwargs["logprobs"] is False

    create.return_value = _FakeAsyncStream()
    monkeypatch.setattr(openai_api_module, "AsyncStream", _FakeAsyncStream)
    events = [
        event
        async for event in api._get_api_stream(
            "[ROLE=USER]\nReply OK",
            LanguageModelGenerationParams(max_tokens=16),
        )
    ]

    assert events
    assert create.await_args.kwargs["temperature"] == 0.2
    assert create.await_args.kwargs["logprobs"] is False
