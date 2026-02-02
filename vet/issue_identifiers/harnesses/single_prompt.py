"""
Simple zero-shot issue identification harness that checks a diff for issues in a single prompt.
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
from vet.imbue_tools.get_conversation_history.input_data_types import CommitInputs
from vet.imbue_tools.repo_utils.context_utils import escape_prompt_markers
from vet.imbue_tools.repo_utils.project_context import ProjectContext
from vet.imbue_tools.types.vet_config import VetConfig
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
from vet.truncation import ContentBudget
from vet.truncation import get_available_tokens
from vet.truncation import get_token_budget
from vet.truncation import truncate_to_token_limit

USER_REQUEST_PREFIX_TEMPLATE = """{{cached_prompt_prefix}}
[ROLE=USER_CACHED]
I'm working on a project, adding commits one after another. The current state of the project is captured by the codebase snapshot above.
{% if extra_context %}
{% if extra_context_truncated %}
Note: Additional context was truncated due to size constraints. Do not assume details about content that is not visible.
{% endif %}
=== ADDITIONAL CONTEXT BEGIN ===
{{ extra_context }}
=== ADDITIONAL CONTEXT END ===
{% endif %}

Assume that I asked for a piece of work to be done by specifying the user request and another programmer has delivered the diff.
{% if include_request_and_diff %}
Below, you can see the user request, as well as the delivered diff. IMPORTANT: The codebase snapshot already includes the changes made in this diff!
{% if goal_truncated %}
Note: The user request was truncated. The full request may contain additional details not shown.
{% endif %}
=== USER REQUEST BEGIN ===
{{ commit_message }}
=== USER REQUEST END ===
{% if diff_truncated %}
Note: The diff below was truncated due to size constraints. Do not assume details about code or context that is not visible.
{% endif %}
=== DIFF BEGIN (unified; lines starting with `-` are removed and `+` are added) ===
{{ unified_diff }}
=== DIFF END ===

{% endif %}{% if not cache_full_prompt %}
[ROLE=USER]{% endif %}
"""


PROMPT_TEMPLATE = (
    USER_REQUEST_PREFIX_TEMPLATE
    + """Your task is to help me verify the quality of the diff.

We care only about specific categories of issues. The rubric below outlines these categories of issues, and contains guidelines and examples to correctly identify them:
{% for issue_type_name, guide in guides.items() %}
[Issue Category {{ loop.index }}: {{ issue_type_name }}]
{{ guide }}
[End of issue category: {{ issue_type_name }}]
{% endfor %}

## Instructions:

1. Look at each category of issues outlined above, one at a time.
2. For each given category, analyze the diff for issues that match the category.
3. For each issue found, provide:
   - issue_code: One of the category names above
   - description: Specific explanation of what's wrong and what a better implementation could be. The description should not exceed a few sentences unless absolutely necessary.
   - location: File path where the issue occurs (if applicable)
   - code_part: Specific code snippet that has the issue (if applicable). Must match exactly, including whitespace. If the code part spans multiple lines, include the exact whitespace and newlines. If there are multiple locations that are relevant to the issue, select a single one to represent the issue.
   - severity: Integer 1-5 (1=minor issue, 5=critical issue that will definitely cause problems)
   - confidence: Float 0.0-1.0 indicating your confidence in this issue
4. When you have identified all issues of the current category, move on to the next category and repeat the process.

Respond with valid JSON that matches this exact schema:

{{ response_schema | tojson(indent=2) }}

Every issue you report must stand on its own, and should not reference other issues in its description.
Do not report duplicate issues with the same or equivalent descriptions within one issue category.
Do not output any issues that are merely based on the absence of information in the codebase snapshot.
Do not speculate about the way a piece of code might get used if that use is not supported by the code included above.
Only raise issues that were introduced by the diff.
It is fine to output an empty list if no issues are found!

IMPORTANT: Do not include any additional commentary outside the JSON response, your response should only contain the JSON object:

```json
{
    "issues": [
        <list of issues>
    ]
}
```
[ROLE=ASSISTANT]
"""
)


class _SinglePromptIssueIdentifier(IssueIdentifier[CommitInputs]):
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
        identifier_inputs: CommitInputs,
    ) -> str:
        # Sort the guides by issue code to ensure prompt caching (and snapshotting in tests) works.
        sorted_guides = sorted(self._identification_guides, key=lambda guide: guide.issue_code)
        formatted_guides = {
            guide.issue_code: format_issue_identification_guide_for_llm(guide) for guide in sorted_guides
        }

        lm_config = config.language_model_generation_config
        available_tokens = get_available_tokens(config)
        goal_budget = get_token_budget(available_tokens, ContentBudget.GOAL)
        extra_context_budget = get_token_budget(available_tokens, ContentBudget.EXTRA_CONTEXT)

        goal, goal_truncated = truncate_to_token_limit(
            identifier_inputs.goal,
            max_tokens=goal_budget,
            count_tokens=lm_config.count_tokens,
            label="goal",
            truncate_end=True,
        )

        extra_context = identifier_inputs.maybe_extra_context or ""
        if extra_context:
            extra_context, extra_context_truncated = truncate_to_token_limit(
                extra_context,
                max_tokens=extra_context_budget,
                count_tokens=lm_config.count_tokens,
                label="extra context",
                truncate_end=True,
            )
            extra_context_truncated = extra_context_truncated or identifier_inputs.extra_context_truncated
        else:
            extra_context_truncated = False

        env = jinja2.Environment(undefined=jinja2.StrictUndefined)
        jinja_template = env.from_string(PROMPT_TEMPLATE)
        return jinja_template.render(
            {
                "include_request_and_diff": True,
                "cached_prompt_prefix": project_context.cached_prompt_prefix,
                "cache_full_prompt": config.cache_full_prompt,
                "extra_context": (escape_prompt_markers(extra_context) if extra_context else None),
                "extra_context_truncated": extra_context_truncated,
                "commit_message": escape_prompt_markers(goal),
                "goal_truncated": goal_truncated or identifier_inputs.goal_truncated,
                "unified_diff": escape_prompt_markers(identifier_inputs.diff),
                "diff_truncated": identifier_inputs.diff_truncated,
                "guides": formatted_guides,
                "response_schema": self._response_schema,
            }
        )

    def identify_issues(
        self,
        identifier_inputs: CommitInputs,
        project_context: ProjectContext,
        config: VetConfig,
    ) -> Generator[GeneratedIssueSchema, None, IssueIdentificationDebugInfo]:
        prompt = self._get_prompt(project_context, config, identifier_inputs)
        language_model = build_language_model_from_config(config.language_model_generation_config)
        language_model_params = LanguageModelGenerationParams(
            temperature=config.temperature,
            max_tokens=config.max_output_tokens,
        )
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

    def input_type(self) -> type[CommitInputs]:
        return CommitInputs

    @property
    def enabled_issue_codes(self) -> tuple[IssueCode, ...]:
        return tuple(guide.issue_code for guide in self._identification_guides)

    @property
    def identifies_code_issues(self) -> bool:
        return True


class SinglePromptHarness(IssueIdentifierHarness[CommitInputs]):
    def make_issue_identifier(
        self, identification_guides: tuple[IssueIdentificationGuide, ...]
    ) -> IssueIdentifier[CommitInputs]:
        return _SinglePromptIssueIdentifier(identification_guides=identification_guides)
