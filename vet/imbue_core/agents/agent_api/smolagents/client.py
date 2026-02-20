import uuid
from contextlib import contextmanager
from typing import Generator
from typing import Iterator
from typing import Self

from loguru import logger
from smolagents import ActionStep
from smolagents import CodeAgent
from smolagents import LiteLLMModel
from smolagents import ToolCallingAgent

from vet.imbue_core.agents.agent_api.client import AgentClient
from vet.imbue_core.agents.agent_api.data_types import AgentMessage
from vet.imbue_core.agents.agent_api.data_types import AgentResultMessage
from vet.imbue_core.agents.agent_api.data_types import AgentSystemEventType
from vet.imbue_core.agents.agent_api.data_types import AgentSystemMessage
from vet.imbue_core.agents.agent_api.data_types import AgentUsage
from vet.imbue_core.agents.agent_api.smolagents.data_types import SmolagentsOptions
from vet.imbue_core.agents.agent_api.smolagents.message_parser import get_step_usage
from vet.imbue_core.agents.agent_api.smolagents.message_parser import parse_smolagents_memory
from vet.imbue_core.agents.agent_api.smolagents.tools import build_safe_tools


class SmolagentsClient(AgentClient[SmolagentsOptions]):
    def __init__(self, options: SmolagentsOptions) -> None:
        super().__init__(options=options)

    @classmethod
    @contextmanager
    def build(cls, options: SmolagentsOptions) -> Generator[Self, None, None]:
        yield cls(options=options)

    def process_query(self, prompt: str) -> Iterator[AgentMessage]:
        logger.trace(
            "{client_name}: calling agent with prompt={prompt}",
            client_name=type(self).__name__,
            prompt=prompt,
        )

        options = self._options
        session_id = str(uuid.uuid4())

        yield AgentSystemMessage(
            event_type=AgentSystemEventType.SESSION_STARTED,
            session_id=session_id,
        )

        cwd = str(options.cwd) if options.cwd else None
        tools = build_safe_tools(cwd=cwd)

        model = LiteLLMModel(model_id=options.model)

        agent_cls = CodeAgent if options.agent_type == "code" else ToolCallingAgent
        agent = agent_cls(
            tools=tools,
            model=model,
            max_steps=options.max_steps,
            verbosity_level=options.verbosity_level,
        )

        try:
            result = agent.run(prompt)

            yield from parse_smolagents_memory(agent.memory)
            usage = _aggregate_usage(agent)

            yield AgentResultMessage(
                session_id=session_id,
                is_error=False,
                result=str(result),
                num_turns=_count_action_steps(agent),
                usage=usage,
            )
        except Exception as e:
            logger.exception(
                "{client_name}: agent error: {error}",
                client_name=type(self).__name__,
                error=str(e),
            )
            if hasattr(agent, "memory"):
                yield from parse_smolagents_memory(agent.memory)
            yield AgentResultMessage(
                session_id=session_id,
                is_error=True,
                error=str(e),
            )

        logger.trace(
            "{client_name}: finished calling agent with prompt={prompt}",
            client_name=type(self).__name__,
            prompt=prompt,
        )


def _count_action_steps(agent: ToolCallingAgent | CodeAgent) -> int:
    return sum(1 for step in agent.memory.steps if isinstance(step, ActionStep))


def _aggregate_usage(agent: ToolCallingAgent | CodeAgent) -> AgentUsage | None:
    total_input = 0
    total_output = 0
    has_usage = False

    for step in agent.memory.steps:
        if isinstance(step, ActionStep):
            usage = get_step_usage(step)
            if usage:
                has_usage = True
                total_input += usage.input_tokens or 0
                total_output += usage.output_tokens or 0

    if not has_usage:
        return None

    return AgentUsage(
        input_tokens=total_input,
        output_tokens=total_output,
        total_tokens=total_input + total_output,
    )
