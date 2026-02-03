import jinja2

from vet.imbue_core.agents.configs import LanguageModelGenerationConfig
from vet.imbue_core.agents.llm_apis.build_apis import build_language_model_from_config
from vet.imbue_core.agents.llm_apis.data_types import CostedLanguageModelResponse
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelGenerationParams
from vet.imbue_core.itertools import only
from vet.vet_types.messages import ConversationMessageUnion
from vet.imbue_tools.get_conversation_history.get_conversation_history import (
    format_conversation_history_for_prompt,
)
from vet.imbue_tools.util_prompts.conversation_prefix import (
    CONVERSATION_PREFIX_TEMPLATE,
)

# TODO: see how this does on actual examples where the agent did something other than what the user asked for
PROMPT_TEMPLATE = (
    CONVERSATION_PREFIX_TEMPLATE
    + """
[ROLE=USER]
What is the user's goal based on the preceding conversation?
Pay attention only to what the user asks for, not what the agent does.
Respond with a brief description of the goal--a few sentences at most.
The goal should be listed as an imperative; for example "Implement XYZ" rather than "The user's goal is to implement XYZ".
Do not include any reasoning or other text in your response.
"""
)

# should be totally sufficient for a goal that's only supposed to be a few sentences
MAX_OUTPUT_TOKENS = 500

GOAL_GENERATION_DEFAULT_PARAMS = LanguageModelGenerationParams(temperature=0.0, max_tokens=MAX_OUTPUT_TOKENS)


def prompt_for_getting_goal_from_conversation(
    conversation_history: tuple[ConversationMessageUnion, ...],
) -> str:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    jinja_template = env.from_string(PROMPT_TEMPLATE)
    formatted_history, conversation_truncated = format_conversation_history_for_prompt(conversation_history)
    return jinja_template.render(
        conversation_history=formatted_history,
        conversation_truncated=conversation_truncated,
    )


def get_goal_from_conversation_with_usage(
    conversation_history: tuple[ConversationMessageUnion, ...],
    language_model_generation_config: LanguageModelGenerationConfig,
) -> CostedLanguageModelResponse:
    """Query an LLM with the conversation history to get the user's goal, and include usage info in the response."""
    language_model = build_language_model_from_config(language_model_generation_config)
    prompt = prompt_for_getting_goal_from_conversation(conversation_history)
    costed_response = language_model.complete_with_usage_sync(
        prompt,
        params=GOAL_GENERATION_DEFAULT_PARAMS,
        is_caching_enabled=language_model.cache_path is not None,
    )
    return costed_response


def get_goal_from_conversation(
    conversation_history: tuple[ConversationMessageUnion, ...],
    language_model_generation_config: LanguageModelGenerationConfig,
) -> str:
    """Query an LLM with the conversation history to get the user's goal."""
    response = only(
        get_goal_from_conversation_with_usage(conversation_history, language_model_generation_config).responses
    )
    return response.text
