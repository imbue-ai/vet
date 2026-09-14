from vet.imbue_core.pydantic_serialization import SerializableModel


class OpenAIModelInfo(SerializableModel):
    cache_write_input_multiplier: float = 1.0
    cache_read_input_multiplier: float = 1.0
    long_context_threshold: int | None = None
    long_context_input_multiplier: float = 1.0
    long_context_output_multiplier: float = 1.0

    object_type: str = "OpenAIModelInfo"


class OpenAICachingInfo(SerializableModel):
    written_to_cache: int = 0

    object_type: str = "OpenAICachingInfo"
