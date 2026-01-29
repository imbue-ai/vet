from imbue_core.pydantic_serialization import SerializableModel


class OpenAIModelInfo(SerializableModel):
    """Currently there isn't any model info specific to OpenAI"""

    object_type: str = "OpenAIModelInfo"


class OpenAICachingInfo(SerializableModel):
    """Currently there isn't any caching info specific to OpenAI"""

    object_type: str = "OpenAICachingInfo"
