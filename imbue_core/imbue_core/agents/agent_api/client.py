import abc
from pathlib import Path
from typing import Generic
from typing import Iterator
from typing import TypeVar

from imbue_core.agents.agent_api.cache_utils import check_cache
from imbue_core.agents.agent_api.cache_utils import update_cache
from imbue_core.agents.agent_api.data_types import AgentMessage
from imbue_core.agents.agent_api.data_types import AgentOptions
from imbue_core.agents.agent_api.interaction import AgentInteraction
from imbue_core.agents.agent_api.interaction import AgentInteractionRecord

AgentOptionsT = TypeVar("AgentOptionsT", bound=AgentOptions)


class AgentClient(abc.ABC, Generic[AgentOptionsT]):
    """Base code agent client interface.

    This client defines the interface for launching and interacting with a coding agent (e.g., ClaudeCode, Codex, etc.)

    Clients are usually created through `get_agent_client`, which selects the right concrete implementation
    and manages any transports. Direct subclasses only need to implement `process_query`.
    """

    def __init__(self, options: AgentOptionsT) -> None:
        self._options = options

    @abc.abstractmethod
    def process_query(self, prompt: str) -> Iterator[AgentMessage]:
        """Call the underlying agent to process a query."""


class RealAgentClient(AgentClient[AgentOptionsT]):
    """Agent client that is not cached or dummy; it runs real commands."""

    @staticmethod
    @abc.abstractmethod
    def _find_cli() -> str:
        """Find the CLI binary for the agent."""

    @classmethod
    @abc.abstractmethod
    def _build_cli_cmd(cls, options: AgentOptionsT) -> list[str]:
        """Build the CLI command for the agent."""

    @staticmethod
    @abc.abstractmethod
    def _build_cli_args(options: AgentOptionsT) -> list[str]:
        """Build the CLI arguments for the agent."""


class CachedAgentClient(AgentClient[AgentOptionsT]):
    """Cached agent client implementation.

    This client is a wrapper around an agent client that caches the agent responses.
    """

    def __init__(self, client: AgentClient[AgentOptionsT], cache_path: Path) -> None:
        super().__init__(client._options)
        self._client = client
        self._cache_path = cache_path

    def process_query(self, prompt: str) -> Iterator[AgentMessage]:
        cache_path = self._cache_path
        if cache_path is not None:
            cache_record = check_cache(cache_path, prompt, self._client._options)
            if cache_record is not None:
                for message in cache_record.messages:
                    yield message
                return

        agent_interaction = AgentInteraction(prompt, self._client._options)
        for message in self._client.process_query(prompt):
            agent_interaction.put(message)
            yield message

        # NOTE we only cache full interactions given the 'process_query' method is called till
        # the generator is exhausted.
        # This means that if the generator is not exhausted, the cache will not be updated.
        # If we do want a way to still cache interactions, even if we early exit the generator,
        # then we could use a separate thread to get the agent response and cache it in the background.
        # See https://gitlab.com/generally-intelligent/generally_intelligent/-/merge_requests/7323#note_2897340073
        agent_interaction_record = AgentInteractionRecord.from_agent_interaction(agent_interaction)
        update_cache(agent_interaction_record, cache_path)

    @property
    def client(self) -> AgentClient[AgentOptionsT]:
        """Get the underlying client."""
        return self._client
