from vet.imbue_core.agents.llm_apis.union_data_types import ProviderSpecificModelInfoUnion
from vet.imbue_core.pydantic_serialization import SerializableModel


class ModelInfo(SerializableModel):
    model_name: str
    cost_per_input_token: float
    cost_per_output_token: float
    max_input_tokens: int
    max_output_tokens: int | None
    # requests per second
    rate_limit_req: float | None = None
    # tokens per second
    rate_limit_tok: float | None = None
    rate_limit_output_tok: float | None = None
    max_thinking_budget: int | None = None
    provider_specific_info: ProviderSpecificModelInfoUnion | None = None
