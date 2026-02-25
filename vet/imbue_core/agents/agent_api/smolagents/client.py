"""Smolagents-based agent client using an OpenAI-compatible model backend."""

import time
import uuid
from contextlib import contextmanager
from typing import Generator
from typing import Iterator
from typing import Self

from loguru import logger

from vet.imbue_core.agents.agent_api.client import AgentClient
from vet.imbue_core.agents.agent_api.data_types import AgentAssistantMessage
from vet.imbue_core.agents.agent_api.data_types import AgentMessage
from vet.imbue_core.agents.agent_api.data_types import AgentResultMessage
from vet.imbue_core.agents.agent_api.data_types import AgentSystemEventType
from vet.imbue_core.agents.agent_api.data_types import AgentSystemMessage
from vet.imbue_core.agents.agent_api.data_types import AgentTextBlock
from vet.imbue_core.agents.agent_api.data_types import AgentUsage
from vet.imbue_core.agents.agent_api.smolagents.data_types import SmolagentsOptions


class SmolagentsClient(AgentClient[SmolagentsOptions]):
    """Agent client backed by smolagents with an OpenAI-compatible model.

    Uses smolagents' ToolCallingAgent with a set of filesystem/search tools
    that mirror the read-only capabilities of the Claude/Codex harnesses.

    Callers should use the context-manager form via `get_agent_client`:

        with get_agent_client(options=SmolagentsOptions(...)) as client:
            for message in client.process_query(prompt):
                ...
    """

    @classmethod
    @contextmanager
    def build(cls, options: SmolagentsOptions) -> Generator[Self, None, None]:
        yield cls(options)

    def process_query(self, prompt: str) -> Iterator[AgentMessage]:
        from smolagents import OpenAIModel
        from smolagents import ToolCallingAgent
        from smolagents.tools import Tool

        from vet.imbue_core.agents.agent_api.smolagents.tools import make_tools

        logger.trace(
            "SmolagentsClient: calling agent with model={model} api_base={api_base}",
            model=self._options.model,
            api_base=self._options.api_base,
        )

        session_id = str(uuid.uuid4())
        start_ms = int(time.monotonic() * 1000)

        yield AgentSystemMessage(
            event_type=AgentSystemEventType.SESSION_STARTED,
            session_id=session_id,
        )

        model = OpenAIModel(
            model_id=self._options.model,
            api_base=self._options.api_base,
            api_key=self._options.api_key,
        )

        tools: list[Tool] = make_tools(cwd=self._options.cwd)
        agent = ToolCallingAgent(tools=tools, model=model)

        try:
            result: str = agent.run(prompt)
        except Exception as e:
            duration_ms = int(time.monotonic() * 1000) - start_ms
            logger.error("SmolagentsClient: agent run failed: {e}", e=e)
            yield AgentResultMessage(
                session_id=session_id,
                is_error=True,
                duration_ms=duration_ms,
                error=str(e),
            )
            return

        duration_ms = int(time.monotonic() * 1000) - start_ms

        # Emit the final answer as an assistant message so downstream
        # consumers that scan AgentAssistantMessage content blocks work.
        yield AgentAssistantMessage(content=[AgentTextBlock(text=str(result))])

        yield AgentResultMessage(
            session_id=session_id,
            is_error=False,
            duration_ms=duration_ms,
            result=str(result),
            usage=AgentUsage(),
        )

        logger.trace(
            "SmolagentsClient: finished in {duration_ms}ms",
            duration_ms=duration_ms,
        )
