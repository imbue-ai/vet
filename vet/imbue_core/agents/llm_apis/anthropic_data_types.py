from vet.imbue_core.pydantic_serialization import SerializableModel


class AnthropicModelInfo(SerializableModel):
    object_type: str = "AnthropicModelInfo"
    cost_per_5m_cache_write_token: float
    cost_per_1h_cache_write_token: float
    cost_per_cache_read_token: float


class AnthropicCachingInfo(SerializableModel):
    object_type: str = "AnthropicCachingInfo"
    # record info on cache writes for 5 minute and 1 hour durations
    written_5m: int
    written_1h: int
