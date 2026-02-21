from typing import Any

from smolagents import ActionStep

from vet.imbue_core.agents.agent_api.data_types import AgentAssistantMessage
from vet.imbue_core.agents.agent_api.data_types import AgentContentBlock
from vet.imbue_core.agents.agent_api.data_types import AgentMessage
from vet.imbue_core.agents.agent_api.data_types import AgentTextBlock
from vet.imbue_core.agents.agent_api.data_types import AgentToolResultBlock
from vet.imbue_core.agents.agent_api.data_types import AgentToolUseBlock
from vet.imbue_core.agents.agent_api.data_types import AgentUsage


def parse_smolagents_memory(memory: Any) -> list[AgentMessage]:
    messages: list[AgentMessage] = []
    for step in memory.steps:
        if isinstance(step, ActionStep):
            messages.extend(_parse_action_step(step))
    return messages


def _parse_action_step(step: ActionStep) -> list[AgentMessage]:
    messages: list[AgentMessage] = []

    reasoning_and_calls: list[AgentContentBlock] = []

    model_output = getattr(step, "model_output", None)
    if model_output is not None:
        content = getattr(model_output, "content", None)
        if isinstance(content, str) and content.strip():
            reasoning_and_calls.append(AgentTextBlock(text=content))

    tool_calls = getattr(step, "tool_calls", None) or []
    for tc in tool_calls:
        tc_id = getattr(tc, "id", None) or f"step_{step.step_number}"
        tc_name = getattr(tc, "name", "unknown")
        tc_args = getattr(tc, "arguments", {})
        reasoning_and_calls.append(
            AgentToolUseBlock(
                id=tc_id,
                name=tc_name,
                input=tc_args if isinstance(tc_args, dict) else {},
            )
        )

    if reasoning_and_calls:
        messages.append(AgentAssistantMessage(content=reasoning_and_calls))

    observations = getattr(step, "observations", None)
    if observations and tool_calls:
        result_blocks: list[AgentContentBlock] = []
        for tc in tool_calls:
            tc_id = getattr(tc, "id", None) or f"step_{step.step_number}"
            result_blocks.append(
                AgentToolResultBlock(
                    tool_use_id=tc_id,
                    content=observations,
                    is_error=False,
                    exit_code=0,
                )
            )
        messages.append(AgentAssistantMessage(content=result_blocks))
    elif observations:
        messages.append(AgentAssistantMessage(content=[AgentTextBlock(text=observations)]))

    error = getattr(step, "error", None)
    if error is not None:
        error_text = str(error)
        messages.append(AgentAssistantMessage(content=[AgentTextBlock(text=f"[Error: {error_text}]")]))

    return messages


def get_step_usage(step: ActionStep) -> AgentUsage | None:
    token_usage = getattr(step, "token_usage", None)
    if token_usage is None:
        return None
    input_tokens = getattr(token_usage, "input_tokens", None)
    output_tokens = getattr(token_usage, "output_tokens", None)
    if input_tokens is None and output_tokens is None:
        return None
    total = (input_tokens or 0) + (output_tokens or 0)
    return AgentUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total if total > 0 else None,
    )
