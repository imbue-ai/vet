import json
from typing import Generator
from typing import Iterable

import jinja2

from vet.imbue_core.data_types import AgenticPhase
from vet.imbue_core.data_types import IssueCode
from vet.imbue_core.data_types import IssueIdentificationDebugInfo
from vet.imbue_core.data_types import IssueIdentificationLLMResponseMetadata
from vet.imbue_core.data_types import LLMResponse
from vet.imbue_tools.get_conversation_history.input_data_types import CommitInputs
from vet.imbue_tools.get_conversation_history.input_data_types import IdentifierInputs
from vet.imbue_tools.get_conversation_history.input_data_types import to_specific_inputs_type
from vet.imbue_tools.repo_utils.context_utils import escape_prompt_markers
from vet.imbue_tools.repo_utils.project_context import ProjectContext
from vet.imbue_tools.types.vet_config import VetConfig
from vet.issue_identifiers.common import GeneratedIssueSchema
from vet.issue_identifiers.common import GeneratedResponseSchema
from vet.issue_identifiers.common import extract_invocation_info_from_messages
from vet.issue_identifiers.common import format_issue_identification_guide_for_llm
from vet.issue_identifiers.common import generate_issues_from_response_texts
from vet.issue_identifiers.common import generate_response_from_agent
from vet.issue_identifiers.common import get_agent_options
from vet.issue_identifiers.identification_guides import IssueIdentificationGuide
from vet.issue_identifiers.utils import ReturnCapturingGenerator

COLLATION_PROMPT_TEMPLATE = """You are reviewing the results from parallel code analysis for potential issues.
Multiple specialized agents analyzed the following code diff, each focusing on a specific type of issue.
The repository files are available in {{ repo_path }}.

### User request ###
{% filter indent(width=2) %}
{{ commit_message }}
{% endfilter %}

### Diff (lines starting with `-` indicate removed code, and lines starting with `+` indicate added code) ###
{% filter indent(width=2) %}
{{ unified_diff }}
{% endfilter %}
###

The rubric below outlines the categories of issues we care about:
{% for issue_code, guide in guides.items() %}
---
**{{ issue_code }}**:
{{ guide }}
{% endfor %}
---

### Parallel Analysis Results ###
{{ generated_issues }}

Your task is to:
1. Review all the findings for accuracy and relevance using the category definitions above
2. Consolidate any duplicate or overlapping issues
3. Ensure each issue is correctly categorized according to the category definitions and re-categorize any issues if necessary
4. Return a consolidated set of issues

Guidelines:
- Merge similar issues that refer to the same underlying problem
- Do not remove any issues, you may only re-categorize or merge issues

After your analysis, provide your response in JSON format matching this schema:

{{ response_schema | tojson(indent=2) }}
"""


def _get_collation_prompt(
    project_context: ProjectContext,
    identifier_inputs: CommitInputs,
    enabled_issue_codes: tuple[IssueCode, ...],
    generated_issues: str,
    guides_by_issue_code: dict[IssueCode, IssueIdentificationGuide],
) -> str:
    # Sort issue codes to make the resulting prompts deterministic (for snapshot tests and LLM caching)
    sorted_issue_codes = sorted(enabled_issue_codes)
    formatted_guides = {
        code: format_issue_identification_guide_for_llm(guides_by_issue_code[code]) for code in sorted_issue_codes
    }

    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    jinja_template = env.from_string(COLLATION_PROMPT_TEMPLATE)

    prompt = jinja_template.render(
        {
            "repo_path": project_context.repo_path,
            "commit_message": escape_prompt_markers(identifier_inputs.goal),
            "unified_diff": escape_prompt_markers(identifier_inputs.diff),
            "guides": formatted_guides,
            "response_schema": GeneratedResponseSchema.model_json_schema(),
            "generated_issues": escape_prompt_markers(generated_issues),
        }
    )
    return prompt


def _convert_parsed_issues_to_combined_string(
    all_parsed_issues: Iterable[GeneratedIssueSchema],
) -> str:
    """Convert all parsed issues from all issue types to a combined string for collation prompt."""
    combined_issues = []

    for issue in all_parsed_issues:
        issue_dict = issue.model_dump()
        for key in ("location", "code_part"):
            if key in issue_dict and issue_dict[key] is None:
                del issue_dict[key]
        combined_issues.append(issue_dict)

    return json.dumps({"issues": combined_issues}, indent=2)


def collate_issues_with_agent(
    issue_generator: Generator[GeneratedIssueSchema, None, IssueIdentificationDebugInfo],
    identifier_inputs: IdentifierInputs,
    project_context: ProjectContext,
    config: VetConfig,
    enabled_issue_codes: tuple[IssueCode, ...],
    guides_by_issue_code: dict[IssueCode, IssueIdentificationGuide],
) -> Generator[GeneratedIssueSchema, None, IssueIdentificationDebugInfo]:
    """
    Collate issues from multiple issue identifiers.

    Args:
        issues: The issues to collate.
        identifier_inputs: The inputs which determine the content provided to the identifiers.
        project_context: Loaded data corresponding to the inputs, e.g. diffs or files.
        config: Settings
        enabled_issue_codes: The issue types used by the issue identifiers.
        guides_by_issue_code: Mapping from issue codes to their identification guides (including any custom overrides).

    Returns:
        A generator of collated issues. Returns IssueIdentificationDebugInfo after the generator is exhausted.

    Raises:
        IdentifierInputsMissingError: If the identifier inputs are missing the commit message or diff, which are required for collation.
    """
    collation_inputs = to_specific_inputs_type(identifier_inputs, CommitInputs)

    all_issues = []
    issue_generator_with_capture = ReturnCapturingGenerator(issue_generator)
    for issue in issue_generator_with_capture:
        all_issues.append(issue)
    issue_generator_debug_info = issue_generator_with_capture.return_value

    options = get_agent_options(
        cwd=project_context.repo_path,
        model_name=config.agent_model_name,
        agent_harness_type=config.agent_harness_type,
    )
    combined_issues_string = _convert_parsed_issues_to_combined_string(all_issues)
    collation_prompt = _get_collation_prompt(
        project_context,
        collation_inputs,
        enabled_issue_codes,
        combined_issues_string,
        guides_by_issue_code,
    )
    response_text, collation_messages = generate_response_from_agent(collation_prompt, options)
    collation_raw_messages = tuple(json.dumps(message.model_dump()) for message in collation_messages)
    collation_invocation_info = extract_invocation_info_from_messages(collation_messages)

    collation_llm_responses = (
        LLMResponse(
            metadata=IssueIdentificationLLMResponseMetadata(
                agentic_phase=AgenticPhase.COLLATION,
                issue_type=None,
            ),
            raw_response=collation_raw_messages,
            invocation_info=collation_invocation_info,
        ),
    )

    yield from generate_issues_from_response_texts(response_texts=(response_text,))

    augmented_debug_info = IssueIdentificationDebugInfo(
        llm_responses=issue_generator_debug_info.llm_responses + collation_llm_responses
    )

    return augmented_debug_info
