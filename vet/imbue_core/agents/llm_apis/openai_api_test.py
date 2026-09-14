from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from openai import NOT_GIVEN
from openai.types.chat import ChatCompletion
from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_message import ChatCompletionMessage

from vet.imbue_core.agents.llm_apis.data_types import CachingInfo
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelGenerationParams
from vet.imbue_core.agents.llm_apis.openai_api import OpenAIChatAPI
from vet.imbue_core.agents.llm_apis.openai_api import OpenAIModelName
from vet.imbue_core.agents.llm_apis.openai_api import _accepts_logprobs_parameter
from vet.imbue_core.agents.llm_apis.openai_data_types import OpenAICachingInfo


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


def test_new_model_long_context_and_cache_pricing() -> None:
    api = OpenAIChatAPI(model_name=OpenAIModelName.GPT_5_6_SOL, cache_path=None)

    assert api.estimate_cost(272_000, 1_000) == pytest.approx(272_000 * 5e-6 + 1_000 * 20e-6)
    assert api.estimate_cost(272_001, 1_000) == pytest.approx(272_001 * 10e-6 + 1_000 * 30e-6)

    caching_info = CachingInfo(
        read_from_cache=100_000,
        provider_specific_data=OpenAICachingInfo(written_to_cache=50_000),
    )
    assert api.calculate_cost(200_000, 1_000, caching_info) == pytest.approx(
        50_000 * 4e-6 + 100_000 * 0.4e-6 + 50_000 * 5e-6 + 1_000 * 20e-6
    )
