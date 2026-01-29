import hashlib
from pathlib import Path

from imbue_core.agents.agent_api.data_types import AgentOptions
from imbue_core.agents.agent_api.interaction import AgentInteractionRecord
from imbue_core.caching import get_cache


def _create_cache_key(prompt: str, options: AgentOptions) -> str:
    """Create a cache key for the given prompt and options."""
    return hashlib.md5(
        f"{prompt} | {options.model_dump_json() if options else ''}".encode()
    ).hexdigest()


def check_cache(
    cache_path: Path, prompt: str, options: AgentOptions
) -> AgentInteractionRecord | None:
    """Check the cache for the given prompt and options."""
    cache_key = _create_cache_key(prompt, options)
    cache = get_cache(cache_path)

    with cache:
        value = cache.get(cache_key)

    if value is None:
        return None
    assert isinstance(
        value, str
    ), f"Got value of type {type(value)} from cache, expected str"
    return AgentInteractionRecord.model_validate_json(value)


def update_cache(
    agent_interaction: AgentInteractionRecord,
    cache_dir: Path,
) -> None:
    """Save an agent interaction record to the cache."""
    cache = get_cache(cache_dir)
    cache_key = _create_cache_key(agent_interaction.prompt, agent_interaction.options)
    with cache:
        cache.set(cache_key, agent_interaction.model_dump_json())
