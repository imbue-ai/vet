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
from vet.imbue_core.pydantic_serialization import SerializableModel
from vet.imbue_tools.get_conversation_history.get_conversation_history import format_conversation_history_for_prompt
from vet.imbue_tools.get_conversation_history.input_data_types import IdentifierInputs
from vet.imbue_tools.llm_output_parsing.parse_model_json_response import ResponseParsingError
from vet.imbue_tools.llm_output_parsing.parse_model_json_response import parse_model_json_response
from vet.imbue_tools.repo_utils.context_utils import escape_prompt_markers
from vet.imbue_tools.repo_utils.project_context import ProjectContext
from vet.imbue_tools.types.vet_config import DEFAULT_CONFIDENCE_THRESHOLD
from vet.imbue_tools.types.vet_config import VetConfig
from vet.imbue_tools.util_prompts.conversation_prefix import CONVERSATION_PREFIX_TEMPLATE
from vet.issue_identifiers.common import GeneratedIssueSchema
from vet.issue_identifiers.common import extract_invocation_info_from_costed_response
from vet.issue_identifiers.common import format_issue_identification_guide_for_llm
from vet.issue_identifiers.harnesses.single_prompt import USER_REQUEST_PREFIX_TEMPLATE
from vet.issue_identifiers.identification_guides import IssueIdentificationGuide
from vet.issue_identifiers.utils import ReturnCapturingGenerator

CODE_BASED_CRITERIA = (
    "1. The issue is based on specific code, and not merely on the absence of information in the codebase snapshot. (true/false)",
    "2. The issue does not speculate about the way a piece of code might get used without having specific knowledge of how it's being used. (true/false)",
    "3. The issues seems important and not overly pedantic. (true/false)",
    "4. The issue was introduced by the diff. (true/false)",
    "5. The issue matches the issue type definition given below. (true/false)",
    "6. The issue flags a piece of code that is already being removed by the diff (line in diff starts with a `-`). (true/false)",
)

CONVERSATION_BASED_CRITERIA = ("1. The issue matches the issue type definition given below. (true/false)",)

PROMPT_TEMPLATE = """Somebody has reviewed the {% if is_code_based_issue %}diff{% else %}conversation history{% endif %} and flagged an issue with it, which you can see here:

### Issue description ###
{% filter indent(width=2) %}
{{ issue_description }}
{% endfilter %}

Please evaluate the issue and determine whether it matches the following criteria:

{% for criterion in criteria %}
{{ criterion }}
{% endfor %}

### Issue type definition ###
{% filter indent(width=2) %}
**{{ issue_code }}**:
{{ guide }}
{% endfilter %}

Please answer the questions above in the form of a JSON object with this exact JSON schema:

{{ response_schema | tojson(indent=2) }}

The keys correspond to the question numbers ("q1" for question 1, "q2" for question 2, and so on), and the values should be boolean values indicating whether the issue matches the criteria (true or false).

IMPORTANT: Do not include any additional commentary outside the JSON response, your response should only contain the JSON object:

```json
{
    "q1": <true|false>,
    "q2": <true|false>,
    ...
}
```
[ROLE=ASSISTANT]
"""


def _get_full_prompt_template(is_code_based_issue: bool) -> str:
    """Get the full prompt template with the appropriate prefix."""
    prefix = USER_REQUEST_PREFIX_TEMPLATE if is_code_based_issue else CONVERSATION_PREFIX_TEMPLATE
    return prefix + PROMPT_TEMPLATE


class CodeBasedEvaluationResponse(SerializableModel):
    q1: bool
    q2: bool
    q3: bool
    q4: bool
    q5: bool
    q6: bool

    def is_passing_result(self) -> bool:
        return all([self.q1, self.q2, self.q3, self.q4, self.q5]) and not self.q6


class ConversationBasedEvaluationResponse(SerializableModel):
    q1: bool

    def is_passing_result(self) -> bool:
        return self.q1


def _format_prompt(
    issue: GeneratedIssueSchema,
    project_context: ProjectContext,
    config: VetConfig,
    inputs: IdentifierInputs,
    is_code_based_issue: bool,
    formatted_guide: str,
) -> str:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    prompt_template = _get_full_prompt_template(is_code_based_issue)
    jinja_template = env.from_string(prompt_template)
    issue_code = IssueCode(issue.issue_code)

    criteria = CODE_BASED_CRITERIA if is_code_based_issue else CONVERSATION_BASED_CRITERIA
    response_class = CodeBasedEvaluationResponse if is_code_based_issue else ConversationBasedEvaluationResponse

    template_vars = {
        "cached_prompt_prefix": project_context.cached_prompt_prefix,
        "cache_full_prompt": config.cache_full_prompt,
        "issue_description": issue.description,
        "issue_code": issue_code,
        "guide": formatted_guide,
        "criteria": criteria,
        "response_schema": response_class.model_json_schema(),
        "is_code_based_issue": is_code_based_issue,
    }

    if is_code_based_issue:
        template_vars["include_request_and_diff"] = True
        template_vars["commit_message"] = escape_prompt_markers(inputs.maybe_goal or "")
        template_vars["unified_diff"] = escape_prompt_markers(inputs.maybe_diff or "")
        template_vars["extra_context"] = (
            escape_prompt_markers(inputs.maybe_extra_context) if inputs.maybe_extra_context else None
        )
    else:
        template_vars["conversation_history"] = format_conversation_history_for_prompt(
            inputs.maybe_conversation_history or ()
        )

    return jinja_template.render(template_vars)


def _parse_response(
    response_text: str, is_code_based_issue: bool
) -> CodeBasedEvaluationResponse | ConversationBasedEvaluationResponse:
    # Fallback value of True for now, since we assume that most issues will pass the evaluation.
    if is_code_based_issue:
        FALLBACK_VALUE = CodeBasedEvaluationResponse(q1=True, q2=True, q3=True, q4=True, q5=True, q6=False)
        response_class = CodeBasedEvaluationResponse
    else:
        FALLBACK_VALUE = ConversationBasedEvaluationResponse(q1=True)
        response_class = ConversationBasedEvaluationResponse

    try:
        return parse_model_json_response(response_text, response_class)
    except ResponseParsingError:
        return FALLBACK_VALUE


def evaluate_code_issue_through_llm(
    issue: GeneratedIssueSchema,
    inputs: IdentifierInputs,
    project_context: ProjectContext,
    config: VetConfig,
    is_code_based_issue: bool,
    formatted_guide: str,
) -> tuple[bool, tuple[LLMResponse, ...]]:
    """
    Args:
        issue: The issue to evaluate.
        inputs: The inputs which determine the content provided to the evaluator.
        project_context: Loaded data corresponding to the inputs, e.g. diffs or files.
        config: Settings for the language model used to evaluate the issue.
        is_code_based_issue: Whether this is a code-based issue (vs conversation-based).

    Returns:
        A tuple containing a boolean indicating whether the issue passes the evaluation and the LLM responses.
        If evaluation fails because the data to judge the issue is missing, the issue is taken to have passed the evaluation.
    """
    if not config.filter_issues_through_llm_evaluator:
        return True, ()

    # Check that we have the required data for evaluation
    if is_code_based_issue:
        if inputs.maybe_goal is None or inputs.maybe_diff is None:
            return True, ()
    else:
        if inputs.maybe_conversation_history is None:
            return True, ()

    language_model = build_language_model_from_config(config.language_model_generation_config)

    prompt = _format_prompt(issue, project_context, config, inputs, is_code_based_issue, formatted_guide)
    costed_response = language_model.complete_with_usage_sync(
        prompt,
        params=LanguageModelGenerationParams(temperature=0.0, max_tokens=config.max_output_tokens),
        is_caching_enabled=language_model.cache_path is not None,
    )

    response = only(costed_response.responses)
    invocation_info = extract_invocation_info_from_costed_response(costed_response)
    results = _parse_response(response.text, is_code_based_issue)

    llm_responses = (
        LLMResponse(
            metadata=IssueIdentificationLLMResponseMetadata(
                agentic_phase=AgenticPhase.FILTRATION,
                issue_type=None,
            ),
            raw_response=(response.text,),
            invocation_info=invocation_info,
        ),
    )

    return results.is_passing_result(), llm_responses


MODEL_CONFIDENCE_THRESHOLD_DEFAULTS: dict[str, float] = {
    "gpt-5.1": 0.0,
}


def get_vet_confidence_threshold(config: VetConfig) -> float:
    model_name = config.language_model_generation_config.model_name

    if model_name in MODEL_CONFIDENCE_THRESHOLD_DEFAULTS:
        return MODEL_CONFIDENCE_THRESHOLD_DEFAULTS[model_name]

    if config.filter_issues_below_confidence is not None:
        return config.filter_issues_below_confidence

    return DEFAULT_CONFIDENCE_THRESHOLD


def evaluate_issue_through_confidence(issue: GeneratedIssueSchema, config: VetConfig) -> bool:
    threshold = get_vet_confidence_threshold(config)
    return issue.confidence >= threshold


def filter_issues(
    issue_generator: Generator[GeneratedIssueSchema, None, IssueIdentificationDebugInfo],
    inputs: IdentifierInputs,
    project_context: ProjectContext,
    config: VetConfig,
    # Currently, the LLM-based filter only works reliably for code-related issue types.
    is_code_based_issue_generator: bool,
    guides_by_issue_code: dict[IssueCode, IssueIdentificationGuide],
) -> Generator[GeneratedIssueSchema, None, IssueIdentificationDebugInfo]:
    """
    Filter issues based on the evaluation.

    Args:
        results: The issues to filter.
        inputs: The inputs which determine the content provided to the evaluator.
        project_context: Loaded data corresponding to the inputs, e.g. diffs or files.
        config: Settings
        guides_by_issue_code: Mapping from issue codes to their identification guides (including any custom overrides).

    Returns:
        A generator of issues with the passes_filtration flag set.
        If evaluation fails because the data to judge the issue is missing, the issue is taken to have passed the evaluation.
        At the end of the generation, returns IssueIdentificationDebugInfo containing the LLM responses.
    """

    filter_llm_responses = []

    issue_generator_with_capture = ReturnCapturingGenerator(issue_generator)
    for issue in issue_generator_with_capture:
        passes_filtration = evaluate_issue_through_confidence(issue, config)
        if passes_filtration:
            issue_code = IssueCode(issue.issue_code)
            formatted_guide = format_issue_identification_guide_for_llm(guides_by_issue_code[issue_code])
            passes_filtration, llm_responses = evaluate_code_issue_through_llm(
                issue,
                inputs,
                project_context,
                config,
                is_code_based_issue_generator,
                formatted_guide,
            )
            filter_llm_responses.extend(llm_responses)
        issue.set_passes_filtration(passes_filtration)
        yield issue
    issue_generator_debug_info = issue_generator_with_capture.return_value

    augmented_debug_info = IssueIdentificationDebugInfo(
        llm_responses=issue_generator_debug_info.llm_responses + tuple(filter_llm_responses)
    )

    return augmented_debug_info
