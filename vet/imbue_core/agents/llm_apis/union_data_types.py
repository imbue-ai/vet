from typing import Annotated

from pydantic import Tag

from vet.imbue_core.agents.llm_apis.anthropic_data_types import AnthropicCachingInfo
from vet.imbue_core.agents.llm_apis.anthropic_data_types import AnthropicModelInfo
from vet.imbue_core.agents.llm_apis.openai_data_types import OpenAICachingInfo
from vet.imbue_core.agents.llm_apis.openai_data_types import OpenAIModelInfo
from vet.imbue_core.pydantic_serialization import build_discriminator

ProviderSpecificModelInfoUnion = Annotated[
    Annotated[AnthropicModelInfo, Tag("AnthropicModelInfo")] | Annotated[OpenAIModelInfo, Tag("OpenAIModelInfo")],
    build_discriminator(),
]

ProviderSpecificCachingInfoUnion = Annotated[
    Annotated[AnthropicCachingInfo, Tag("AnthropicCachingInfo")]
    | Annotated[OpenAICachingInfo, Tag("OpenAICachingInfo")],
    build_discriminator(),
]
