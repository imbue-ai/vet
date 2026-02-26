from vet.imbue_core.agents.llm_apis.anthropic_api import ANTHROPIC_MODEL_INFO_BY_NAME
from vet.imbue_core.agents.llm_apis.anthropic_api import AnthropicModelName
from vet.imbue_core.agents.llm_apis.gemini_api import GEMINI_MODEL_INFO_BY_NAME
from vet.imbue_core.agents.llm_apis.gemini_api import GeminiModelName
from vet.imbue_core.agents.llm_apis.mock_api import MY_MOCK_MODEL_INFO
from vet.imbue_core.agents.llm_apis.models import ModelInfo
from vet.imbue_core.agents.llm_apis.openai_api import OpenAIModelName
from vet.imbue_core.agents.llm_apis.openai_api import get_model_info as get_openai_model_info

ModelName = AnthropicModelName | OpenAIModelName | GeminiModelName


def get_model_info_from_name(model_name: str) -> ModelInfo:
    if model_name == MY_MOCK_MODEL_INFO.model_name:
        return MY_MOCK_MODEL_INFO
    if model_name in (v for v in AnthropicModelName):
        return ANTHROPIC_MODEL_INFO_BY_NAME[AnthropicModelName(model_name)]
    elif model_name in (v for v in OpenAIModelName):
        return get_openai_model_info(OpenAIModelName(model_name))
    elif model_name in (v for v in GeminiModelName):
        return GEMINI_MODEL_INFO_BY_NAME[GeminiModelName(model_name)]
    else:
        raise Exception(f"Unknown model: {model_name}")


def get_model_max_context_length(model_name: str) -> int:
    model_info = get_model_info_from_name(model_name)
    return model_info.max_input_tokens


def get_model_max_output_tokens(model_name: str) -> int:
    model_info = get_model_info_from_name(model_name)
    if model_info.max_output_tokens is None:
        raise ValueError(f"Model {model_name} does not have max_output_tokens defined")
    return model_info.max_output_tokens


def get_all_model_names() -> list[str]:
    names = []
    names.extend(list(v for v in AnthropicModelName))
    names.extend(list(v for v in OpenAIModelName))
    names.extend(list(v for v in GeminiModelName))
    return names


def get_formatted_model_name(model_name: str) -> str:
    """Get a nicely formatted model name.

        Does things like removing generic prefixes like 'models/' and forward slashes (which can interfere with file names).

        Some examples:

    - 'models/gemini-2.5-flash' -> 'gemini-2.5-flash'
    - 'groq/llama-3.3-70b-versatile' -> 'groq-llama-3.3-70b-versatile'
    - 'claude-opus-4-6' -> 'claude-opus-4-6'

    """
    if model_name.startswith("models/"):
        model_name = model_name[len("models/") :]
    return model_name.replace("/", "-")
