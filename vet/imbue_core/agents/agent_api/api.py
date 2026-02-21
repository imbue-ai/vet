from __future__ import annotations

from contextlib import contextmanager
from functools import singledispatch
from pathlib import Path
from typing import Any
from typing import ContextManager
from typing import Iterator

from vet.imbue_core.agents.agent_api.claude.client import ClaudeCodeClient
from vet.imbue_core.agents.agent_api.claude.data_types import ClaudeCodeOptions
from vet.imbue_core.agents.agent_api.client import AgentClient
from vet.imbue_core.agents.agent_api.client import AgentOptionsT
from vet.imbue_core.agents.agent_api.client import CachedAgentClient
from vet.imbue_core.agents.agent_api.codex.client import CodexClient
from vet.imbue_core.agents.agent_api.codex.data_types import CodexOptions
from vet.imbue_core.agents.agent_api.data_types import AgentOptions
from vet.imbue_core.agents.agent_api.opencode.client import OpenCodeClient
from vet.imbue_core.agents.agent_api.opencode.data_types import OpenCodeOptions


@singledispatch
def _build_client_from_options(
    options: AgentOptions,
) -> ContextManager[AgentClient[Any]]:
    """Return a context manager that builds an AgentClient for the given options."""
    raise ValueError(f"Unsupported agent options type: {type(options).__name__}")


@_build_client_from_options.register
def _(options: ClaudeCodeOptions) -> ContextManager[AgentClient[ClaudeCodeOptions]]:
    return ClaudeCodeClient.build(options)


@_build_client_from_options.register
def _(options: CodexOptions) -> ContextManager[AgentClient[CodexOptions]]:
    return CodexClient.build(options)


@_build_client_from_options.register
def _(options: OpenCodeOptions) -> ContextManager[AgentClient[OpenCodeOptions]]:
    return OpenCodeClient.build(options)


@contextmanager
def get_agent_client(
    *,
    options: AgentOptionsT,
    cache_path: Path | None = None,
) -> Iterator[AgentClient[AgentOptionsT]]:
    """Build and manage the lifecycle of an AgentClient based on the provided options.

    Args:
        options: AgentOptions instance describing which agent to run.
        cache_path: Optional path to use for caching agent interactions.

    Yields:
        An AgentClient (or CachedAgentClient) bound to the selected agent implementation.
    """

    with _build_client_from_options(options) as client:
        if cache_path is None:
            yield client
            return

        yield CachedAgentClient(client, cache_path)
