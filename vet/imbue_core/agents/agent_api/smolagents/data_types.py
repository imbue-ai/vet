from typing import Literal

from vet.imbue_core.agents.agent_api.data_types import AgentOptions


class SmolagentsOptions(AgentOptions):
    """Options for the smolagents-based agent harness.

    Only OpenAI-compatible models are supported. The api_base and api_key
    must be resolved from the user's models.json before constructing this object.
    """

    object_type: Literal["SmolagentsOptions"] = "SmolagentsOptions"

    # The actual API model ID (e.g. "claude-sonnet-4-6", not the user-facing alias).
    model: str
    # The OpenAI-compatible base URL for the provider.
    api_base: str
    # The resolved API key value (not the env var name).
    api_key: str
