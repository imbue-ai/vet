import asyncio
import enum
from pathlib import Path
from typing import AsyncGenerator

import toml
from loguru import logger
from pydantic.fields import Field
from pydantic.functional_validators import field_validator

from vet.imbue_core.agents.llm_apis.data_types import CostedLanguageModelResponse
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelGenerationParams
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelResponse
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelResponseUsage
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelResponseWithLogits
from vet.imbue_core.agents.llm_apis.data_types import ResponseStopReason
from vet.imbue_core.agents.llm_apis.data_types import TokenProbability
from vet.imbue_core.agents.llm_apis.language_model_api import LanguageModelAPI
from vet.imbue_core.agents.llm_apis.models import ModelInfo
from vet.imbue_core.agents.llm_apis.stream import LanguageModelStreamDeltaEvent
from vet.imbue_core.agents.llm_apis.stream import LanguageModelStreamEndEvent
from vet.imbue_core.agents.llm_apis.stream import LanguageModelStreamEvent
from vet.imbue_core.itertools import only
from vet.imbue_core.pydantic_serialization import MutableModel


class MockModelName(enum.StrEnum):
    MOCK_MODEL = "my-mock-model"


MY_MOCK_MODEL_INFO = ModelInfo(
    model_name=MockModelName.MOCK_MODEL,
    cost_per_input_token=0.0 / 1_000_000,
    cost_per_output_token=0.0 / 1_000_000,
    max_input_tokens=32_768,
    max_output_tokens=None,
)


class Stats(MutableModel):
    complete_calls: int = 0


class LanguageModelMock(LanguageModelAPI):
    model_name: str = MY_MOCK_MODEL_INFO.model_name
    cache_path: Path | None = None
    # FIXME: can't have a mutable class inside a frozen pydantic model
    stats: Stats = Field(default_factory=Stats)

    @property
    def model_info(self) -> ModelInfo:
        return MY_MOCK_MODEL_INFO

    async def complete(
        self,
        prompt: str,
        params: LanguageModelGenerationParams,
        is_caching_enabled: bool = True,
    ) -> tuple[LanguageModelResponse, ...]:
        raise NotImplementedError()

    def _get_token_probabilities(self, response_text: str) -> tuple[tuple[TokenProbability, ...], ...]:
        return tuple(
            (TokenProbability(token=pseudo_token, log_probability=0.0, is_stop=False),)
            for pseudo_token in response_text.split()
        )

    async def _call_api(
        self,
        prompt: str,
        params: LanguageModelGenerationParams,
        network_failure_count: int = 0,
    ) -> CostedLanguageModelResponse:
        raise NotImplementedError()

    def _get_api_stream(
        self,
        prompt: str,
        params: LanguageModelGenerationParams,
    ) -> AsyncGenerator[LanguageModelStreamEvent, None]:
        # TODO Implement streaming support (?)
        raise NotImplementedError()


MOCK_STREAM_SLEEP_TIME = 5.0


class FileBasedLanguageModelMock(LanguageModelMock):
    """
    A mock LLM API that reads responses from a toml file.
    The response can either be identified using the toml key or a prompt which is part of the toml dictionary.
    """

    calls: int = 0

    @field_validator("cache_path")  # pyre-ignore[56]: pyre doesn't understand pydantic
    @classmethod
    def validate_cache_path(cls, v: Path | None) -> Path | None:
        if v is None:
            raise ValueError("Mock responses file path is not set.")
        if not v.exists():
            raise ValueError(f"Mock responses file {v} does not exist.")
        if not v.suffix == ".toml":
            raise ValueError(f"Mock responses file {v} is not a toml file.")
        return v

    def _get_user_message_from_prompt(self, prompt: str) -> str:
        user_prompt = prompt.rsplit("[ROLE=USER]", 1)[-1].strip()
        return user_prompt

    def get_single_response(self, prompt: str) -> str:
        return only(self.get_parts_of_response(prompt))

    def get_parts_of_response(self, prompt: str) -> tuple[str, ...]:
        """
        Support both of the following possible identifiers:
        [identifier]
        prompt = "user message here"
        [[identifier.responses]]
        text = "response"
        [[identifier.responses]]
        text = "response2"

        [identifier]
        prompt = "user message here"
        response = "response"
        """
        # this is checked during validation but i guess the type checker doesn't see it
        assert self.cache_path is not None
        # TODO: should we try something that is not toml? toml formatting is a little annoying
        toml_dict = toml.load(self.cache_path)
        # TODO: currently the identifier is the last user message, because the entire prompt is really long
        #  if we need to support the same user message with different responses, expand this, maybe chat history?
        identifier = self._get_user_message_from_prompt(prompt)
        logger.debug("Getting response for identifier: {} from {}", identifier, toml_dict)
        toml_item = toml_dict.get(identifier, None)
        if toml_item is None:
            for toml_key, response in toml_dict.items():
                if "prompt" in response:
                    if response["prompt"] == identifier:
                        toml_item = response
                        break
        if toml_item is None:
            raise KeyError(f"No response found for the given identifier {identifier}")

        if "responses" in toml_item:
            responses = toml_item["responses"]
            if isinstance(responses, list):
                return tuple(r["text"] for r in responses if isinstance(r, dict) and "text" in r)
            raise ValueError(f"Expected 'responses' to be a list of tables in section '{identifier}'")

        if "response" in toml_item:
            return (str(toml_item["response"]),)

        raise ValueError(f"No valid response or responses found for identifier '{identifier}'")

    async def complete(
        self,
        prompt: str,
        params: LanguageModelGenerationParams,
        is_caching_enabled: bool = True,
    ) -> tuple[LanguageModelResponse, ...]:
        response = self.get_single_response(prompt)
        self.stats.complete_calls += 1
        token_probabilities = self._get_token_probabilities(response)
        return (
            LanguageModelResponseWithLogits(
                text=response,
                token_count=len(token_probabilities),
                stop_reason=ResponseStopReason.NONE,
                network_failure_count=0,
                token_probabilities=token_probabilities,
            ),
        )

    async def _get_api_stream(
        self,
        prompt: str,
        params: LanguageModelGenerationParams,
    ) -> AsyncGenerator[LanguageModelStreamEvent, None]:
        responses = self.get_parts_of_response(prompt)
        self.stats.complete_calls += 1
        if len(responses) == 1:
            response = responses[0]
            yield LanguageModelStreamDeltaEvent(delta=response)
        else:
            for response in responses:
                yield LanguageModelStreamDeltaEvent(delta=response)
                await asyncio.sleep(MOCK_STREAM_SLEEP_TIME)
        yield LanguageModelStreamEndEvent(
            usage=LanguageModelResponseUsage(prompt_tokens_used=0, completion_tokens_used=0, dollars_used=0),
            stop_reason=ResponseStopReason.NONE,
        )
