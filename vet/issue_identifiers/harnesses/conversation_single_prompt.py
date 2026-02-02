"""
Single-prompt issue identification harness that operates on the conversation history.

Currently hard-coded to check for misleading behavior in a conversation.
"""

from functools import cached_property
from typing import Any
from typing import Generator

import jinja2

from vet.imbue_core.agents.llm_apis.build_apis import build_language_model_from_config
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelGenerationParams
from vet.imbue_core.data_types import AgenticPhase
from vet.imbue_core.data_types import IssueCode
from vet.imbue_core.data_types import IssueIdentificationDebugInfo
from vet.imbue_core.data_types import IssueIdentificationLLMResponseMetadata
from vet.imbue_core.data_types import LLMResponse
from vet.imbue_core.itertools import only
from vet.imbue_tools.get_conversation_history.get_conversation_history import (
    format_conversation_history_for_prompt,
)
from vet.imbue_tools.get_conversation_history.input_data_types import ConversationInputs
from vet.imbue_tools.repo_utils.project_context import ProjectContext
from vet.imbue_tools.types.vet_config import VetConfig
from vet.imbue_tools.util_prompts.conversation_prefix import (
    CONVERSATION_PREFIX_TEMPLATE,
)
from vet.issue_identifiers.base import IssueIdentifier
from vet.issue_identifiers.common import GeneratedIssueSchema
from vet.issue_identifiers.common import GeneratedResponseSchema
from vet.issue_identifiers.common import (
    extract_invocation_info_from_costed_response,
)
from vet.issue_identifiers.common import (
    format_issue_identification_guide_for_llm,
)
from vet.issue_identifiers.common import generate_issues_from_response_texts
from vet.issue_identifiers.harnesses.base import IssueIdentifierHarness
from vet.issue_identifiers.identification_guides import (
    IssueIdentificationGuide,
)
from vet.truncation import ContextBudget
from vet.truncation import get_available_tokens
from vet.truncation import get_token_budget

PROMPT_TEMPLATE = (
    CONVERSATION_PREFIX_TEMPLATE
    + """
{% if cache_full_prompt %}[ROLE=USER_CACHED]{% else %}[ROLE=USER]{% endif %}{% if instruction_context %}
Here are the instruction files that were provided to the agent:
{{ instruction_context }}{% endif %}

Your task is to examine the conversation history to find events of interest.
These events will be used to generate suggestions for what the agent should do next to best achieve the user's goal.
We care only about specific categories of events. The rubric below outlines these categories of events, and contains guidelines and examples to correctly identify them:
{% for guide_name, guide in guides.items() %}
---
**{{ guide_name }}**:
{{ guide }}

{% endfor %}
---

Respond with valid JSON that matches this exact schema:

{{ response_schema | tojson(indent=2) }}

[ROLE=ASSISTANT]
"""
)


class _ConversationSinglePromptIssueIdentifier(IssueIdentifier[ConversationInputs]):
    _identification_guides: tuple[IssueIdentificationGuide, ...]

    def __init__(self, identification_guides: tuple[IssueIdentificationGuide, ...]) -> None:
        self._identification_guides = identification_guides

    @cached_property
    def _response_schema(self) -> dict[str, Any]:
        return GeneratedResponseSchema.model_json_schema()

    def _get_prompt(
        self,
        project_context: ProjectContext,
        config: VetConfig,
        identifier_inputs: ConversationInputs,
    ) -> str:
        # Sort the guides by issue code to ensure prompt caching (and snapshotting in tests) works.
        sorted_guides = sorted(self._identification_guides, key=lambda guide: guide.issue_code)
        formatted_guides = {
            guide.issue_code: format_issue_identification_guide_for_llm(guide) for guide in sorted_guides
        }

        lm_config = config.language_model_generation_config
        available_tokens = get_available_tokens(config)
        conversation_budget = get_token_budget(available_tokens, ContextBudget.CONVERSATION)

        conversation_history, conversation_truncated = format_conversation_history_for_prompt(
            identifier_inputs.conversation_history,
            max_tokens=conversation_budget,
            count_tokens=lm_config.count_tokens,
        )

        env = jinja2.Environment(undefined=jinja2.StrictUndefined)
        jinja_template = env.from_string(PROMPT_TEMPLATE)
        return jinja_template.render(
            cached_prompt_prefix=project_context.cached_prompt_prefix,
            cache_full_prompt=config.cache_full_prompt,
            conversation_history=conversation_history,
            conversation_truncated=conversation_truncated or identifier_inputs.conversation_truncated,
            # pyre-fixme[16]: SubrepoContext need not have a formatted_repo_context, and instruction_context can be None
            instruction_context=project_context.instruction_context.formatted_repo_context,
            response_schema=self._response_schema,
            guides=formatted_guides,
        )

    def identify_issues(
        self,
        identifier_inputs: ConversationInputs,
        project_context: ProjectContext,
        config: VetConfig,
    ) -> Generator[GeneratedIssueSchema, None, IssueIdentificationDebugInfo]:
        language_model = build_language_model_from_config(config.language_model_generation_config)
        language_model_params = LanguageModelGenerationParams(
            temperature=config.temperature,
            max_tokens=config.max_output_tokens,
        )
        prompt = self._get_prompt(project_context, config, identifier_inputs)
        costed_response = language_model.complete_with_usage_sync(
            prompt,
            params=language_model_params,
            is_caching_enabled=language_model.cache_path is not None,
        )

        response = only(costed_response.responses)
        invocation_info = extract_invocation_info_from_costed_response(costed_response)

        llm_responses = (
            LLMResponse(
                metadata=IssueIdentificationLLMResponseMetadata(agentic_phase=AgenticPhase.ISSUE_IDENTIFICATION),
                raw_response=(response.text,),
                invocation_info=invocation_info,
            ),
        )

        yield from generate_issues_from_response_texts(response_texts=(response.text,))

        return IssueIdentificationDebugInfo(llm_responses=llm_responses)

    def input_type(self) -> type[ConversationInputs]:
        return ConversationInputs

    @property
    def enabled_issue_codes(self) -> tuple[IssueCode, ...]:
        return tuple(guide.issue_code for guide in self._identification_guides)

    @property
    def identifies_code_issues(self) -> bool:
        return False


class ConversationSinglePromptHarness(IssueIdentifierHarness[ConversationInputs]):
    def make_issue_identifier(
        self, identification_guides: tuple[IssueIdentificationGuide, ...]
    ) -> IssueIdentifier[ConversationInputs]:
        return _ConversationSinglePromptIssueIdentifier(identification_guides=identification_guides)
