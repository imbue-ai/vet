from __future__ import annotations

from unittest.mock import AsyncMock
from unittest.mock import patch

import httpx
import pytest
from openai import NOT_GIVEN
from openai.types.chat import ChatCompletion
from openai.types.chat import ChatCompletionMessage
from openai.types.chat.chat_completion import Choice

from vet.imbue_core.agents.llm_apis.data_types import LanguageModelGenerationParams
from vet.imbue_core.agents.llm_apis.openai_compatible_api import OpenAICompatibleAPI


def _make_chat_completion(text: str = "response") -> ChatCompletion:
    return ChatCompletion(
        id="test-id",
        created=0,
        model="test-model",
        object="chat.completion",
        choices=[
            Choice(
                index=0,
                message=ChatCompletionMessage(role="assistant", content=text),
                finish_reason="stop",
            )
        ],
        usage=None,
    )


def _make_api(supports_temperature: bool = True) -> OpenAICompatibleAPI:
    return OpenAICompatibleAPI(
        model_name="test-model",
        base_url="https://example.com/v1",
        api_key_env="",
        context_window=128000,
        max_output_tokens=16384,
        supports_temperature=supports_temperature,
        cache_path=None,
    )


class TestSupportsTemperature:
    @pytest.mark.anyio
    async def test_temperature_sent_when_supported(self) -> None:
        api = _make_api(supports_temperature=True)
        completion = _make_chat_completion("ok")
        mock_create = AsyncMock(return_value=completion)

        with patch.object(api, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = mock_create
            mock_get_client.return_value = mock_client

            await api._call_api(
                prompt="[ROLE=USER]\nHello",
                params=LanguageModelGenerationParams(temperature=0.5, max_tokens=100),
            )

        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["temperature"] == 0.5

    @pytest.mark.anyio
    async def test_temperature_omitted_when_not_supported(self) -> None:
        api = _make_api(supports_temperature=False)
        completion = _make_chat_completion("ok")
        mock_create = AsyncMock(return_value=completion)

        with patch.object(api, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = mock_create
            mock_get_client.return_value = mock_client

            await api._call_api(
                prompt="[ROLE=USER]\nHello",
                params=LanguageModelGenerationParams(temperature=0.0, max_tokens=100),
            )

        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["temperature"] is NOT_GIVEN

    @pytest.mark.anyio
    async def test_default_supports_temperature_is_true(self) -> None:
        api = OpenAICompatibleAPI(
            model_name="test-model",
            base_url="https://example.com/v1",
            api_key_env="",
            context_window=128000,
            max_output_tokens=16384,
            cache_path=None,
        )
        assert api.supports_temperature is True


class TestSupportsTemperatureConfig:
    def test_supports_temperature_in_model_config(self) -> None:
        from vet.cli.config.schema import ModelConfig

        config = ModelConfig(
            context_window=128000, max_output_tokens=16384, supports_temperature=False
        )
        assert config.supports_temperature is False

    def test_supports_temperature_is_required(self) -> None:
        from pydantic import ValidationError

        from vet.cli.config.schema import ModelConfig

        with pytest.raises(ValidationError):
            ModelConfig(context_window=128000, max_output_tokens=16384)

    def test_build_language_model_config_passes_supports_temperature(self) -> None:
        from vet.cli.config.loader import build_language_model_config
        from vet.cli.config.schema import ModelConfig
        from vet.cli.config.schema import ModelsConfig
        from vet.cli.config.schema import ProviderConfig
        from vet.imbue_core.agents.configs import OpenAICompatibleModelConfig

        user_config = ModelsConfig(
            providers={
                "test": ProviderConfig(
                    base_url="https://example.com/v1",
                    api_key_env="TEST_KEY",
                    models={
                        "reasoning-model": ModelConfig(
                            context_window=128000,
                            max_output_tokens=16384,
                            supports_temperature=False,
                        ),
                        "normal-model": ModelConfig(
                            context_window=128000,
                            max_output_tokens=16384,
                            supports_temperature=True,
                        ),
                    },
                )
            }
        )

        reasoning_config = build_language_model_config("reasoning-model", user_config)
        assert isinstance(reasoning_config, OpenAICompatibleModelConfig)
        assert reasoning_config.custom_supports_temperature is False

        normal_config = build_language_model_config("normal-model", user_config)
        assert isinstance(normal_config, OpenAICompatibleModelConfig)
        assert normal_config.custom_supports_temperature is True
