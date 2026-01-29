import abc
import asyncio
from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Any
from typing import AsyncGenerator
from typing import Sequence

import anyio

from imbue_core.agents.llm_apis.data_types import CachedCostedLanguageModelResponse
from imbue_core.agents.llm_apis.data_types import CostedLanguageModelResponse
from imbue_core.agents.llm_apis.data_types import LanguageModelResponse
from imbue_core.agents.llm_apis.data_types import LanguageModelResponseUsage
from imbue_core.agents.llm_apis.data_types import LanguageModelStreamInputs
from imbue_core.agents.llm_apis.data_types import ModelResponse
from imbue_core.agents.llm_apis.data_types import ResponseStopReason
from imbue_core.agents.primitives.resource_limits import PaymentAuthorization
from imbue_core.agents.primitives.resource_limits import get_global_resource_limits
from imbue_core.caching import AsyncCache
from imbue_core.pydantic_serialization import SerializableModel


class LanguageModelStreamStartEvent(SerializableModel):
    pass


class LanguageModelStreamDeltaEvent(SerializableModel):
    delta: str
    # TODO add per delta token count (if there is a demand)
    # TODO add per delta logprobs (if there is a demand)


class LanguageModelStreamEndEvent(SerializableModel):
    usage: LanguageModelResponseUsage
    stop_reason: ResponseStopReason


LanguageModelStreamEvent = (
    LanguageModelStreamStartEvent
    | LanguageModelStreamDeltaEvent
    | LanguageModelStreamEndEvent
)


class LanguageModelStreamCallback(abc.ABC, SerializableModel):
    @abc.abstractmethod
    async def __call__(self, response: CostedLanguageModelResponse) -> None: ...


class UpdateCacheCallback(LanguageModelStreamCallback):
    key: str
    cache: AsyncCache[CachedCostedLanguageModelResponse]
    api_inputs: LanguageModelStreamInputs | None

    async def __call__(self, response: CostedLanguageModelResponse) -> None:
        async with self.cache:
            await self.cache.set(
                self.key,
                CachedCostedLanguageModelResponse(
                    response=response, inputs=self.api_inputs
                ),
            )


class PromptDebuggingCallback(LanguageModelStreamCallback):
    prompt: str
    output_path: anyio.Path

    async def __call__(self, response: CostedLanguageModelResponse) -> None:
        await self.output_path.write_text(self.prompt + response.responses[0].text)


class SettleSpendCallback(LanguageModelStreamCallback):
    auth: PaymentAuthorization

    async def __call__(self, response: CostedLanguageModelResponse) -> None:
        dollars_used = response.usage.dollars_used
        global_resource_limits = get_global_resource_limits()
        assert global_resource_limits is not None
        await global_resource_limits.settle_spend(self.auth, dollars_used)
        return None


async def consume_async_iterator(iterator: AsyncIterator[Any]) -> None:
    async for _ in iterator:
        ...


async def get_cached_response_stream(
    response: CostedLanguageModelResponse,
) -> AsyncGenerator[LanguageModelStreamEvent, None]:
    """Simple stream that return cached response in a single go.

    Implemented here so user get's a consistent interface from stream().
    """
    yield LanguageModelStreamStartEvent()
    yield LanguageModelStreamDeltaEvent(delta=response.responses[0].text)
    yield LanguageModelStreamEndEvent(
        usage=response.usage, stop_reason=response.responses[0].stop_reason
    )


class StreamedLanguageModelResponse(ModelResponse):
    """A stream of LanguageModel API events."""

    text_stream: AsyncIterator[str]

    def __init__(
        self,
        # Note event_stream is AsyncGenerator as it supports aclose for better cleanup (unlike AsyncIterator)
        event_stream: AsyncGenerator[LanguageModelStreamEvent, None],
        network_failure_count: int,
        completion_callbacks: Sequence[LanguageModelStreamCallback] = (),
    ) -> None:
        # the underlying stream coming from the API
        self._event_stream = event_stream
        self.text_stream = self._stream_text()
        self._final_message_snapshot: LanguageModelResponse | None = None

        self._completion_callbacks = completion_callbacks
        # this is propogated to final message
        self._network_failure_count = network_failure_count
        self.stop_reason: ResponseStopReason | None = None

    async def get_final_message(self) -> LanguageModelResponse:
        # wait until final message
        await consume_async_iterator(self._event_stream)
        assert self._final_message_snapshot is not None
        return self._final_message_snapshot

    async def __aiter__(self) -> AsyncGenerator[LanguageModelStreamEvent, None]:
        # iterator of events, with handling of shutdown
        async with aclosing(self._event_stream) as event_stream:
            deltas: list[str] = []
            async for event in event_stream:
                if isinstance(event, LanguageModelStreamStartEvent):
                    # Need nested if statement here for outer if-elif-else to correctly filter for unknown event types
                    if len(deltas) > 0 or self._final_message_snapshot is not None:
                        raise RuntimeError(
                            "Start event should be the first event in stream."
                        )
                elif isinstance(event, LanguageModelStreamDeltaEvent):
                    deltas.append(event.delta)
                elif isinstance(event, LanguageModelStreamEndEvent):
                    self.stop_reason = event.stop_reason
                    self._final_message_snapshot = LanguageModelResponse(
                        text="".join(deltas),
                        token_count=(
                            0
                            if event.usage is None
                            else event.usage.completion_tokens_used
                        ),
                        stop_reason=event.stop_reason,
                        network_failure_count=self._network_failure_count,
                    )
                    if self._completion_callbacks is not None:
                        costed_response = CostedLanguageModelResponse(
                            usage=event.usage, responses=(self._final_message_snapshot,)
                        )
                        await asyncio.gather(
                            *[
                                callback(costed_response)
                                for callback in self._completion_callbacks
                            ]
                        )
                else:
                    raise ValueError(
                        f"Unknown or Unexpected StreamEvent type {type(event)}."
                    )

                yield event

    async def _stream_text(self) -> AsyncIterator[str]:
        # iterator of text delta
        async for event in self:
            if isinstance(event, LanguageModelStreamDeltaEvent):
                yield event.delta

    async def __aenter__(self) -> "StreamedLanguageModelResponse":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close iterator."""
        # clean up underlying stream (currently not sure how to do this/if we need to do this)
        await self._event_stream.aclose()
