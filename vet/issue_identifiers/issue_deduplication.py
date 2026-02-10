import json
import time
from typing import Generator
from typing import Iterable

import jinja2
from loguru import logger

from vet.imbue_core.agents.llm_apis.build_apis import build_language_model_from_config
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelGenerationParams
from vet.imbue_core.data_types import AgenticPhase
from vet.imbue_core.data_types import IssueCode
from vet.imbue_core.data_types import IssueIdentificationDebugInfo
from vet.imbue_core.data_types import IssueIdentificationLLMResponseMetadata
from vet.imbue_core.data_types import LLMResponse
from vet.imbue_core.itertools import only
from vet.imbue_tools.repo_utils.context_utils import escape_prompt_markers
from vet.imbue_tools.types.vet_config import VetConfig
from vet.issue_identifiers.common import GeneratedIssueSchema
from vet.issue_identifiers.common import GeneratedResponseSchema
from vet.issue_identifiers.common import (
    extract_invocation_info_from_costed_response,
)
from vet.issue_identifiers.common import (
    format_issue_identification_guide_for_llm,
)
from vet.issue_identifiers.common import generate_issues_from_response_texts
from vet.issue_identifiers.identification_guides import (
    ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE,
)
from vet.issue_identifiers.utils import ReturnCapturingGenerator

DEDUPLICATION_PROMPT_TEMPLATE = """[ROLE=USER]
You are reviewing the results from parallel code analysis for potential issues.
Multiple specialized checks analyzed the work of an automated coding agent, each focusing on checking for a specific type of issue.

The rubric below outlines the categories of issues we care about:
{% for issue_code, guide in guides.items() %}
---
**{{ issue_code }}**:
{{ guide }}
{% endfor %}
---

### Individual Analysis Results ###
{{ generated_issues }}

Your task is to:
1. Consolidate any duplicate issues
2. If duplicates are categorized as different issue types, pick the most appropriate issue type for the merged issue according to the category definitions above.
3. Return the consolidated set of issues

Guidelines:
- Merge issues that refer to the same underlying problem and would be solved by the same fix. Make sure that their locations (if available) are the same, and that their descriptions describe the same underlying problem. The issue_code and other properties can be different.
- A merged issue should represent a single problem. Never merge multiple distinct problems, even if they are closely related or share the same location.
- Never merge issues that refer to different locations, functions or files.
- Do not remove any issues, you may only re-categorize or merge issues
- When merging issues, pick A SINGLE most relevant location + code_part pair from the issues that you are merging together. NEVER try to combine multiple locations or code_part into one. Just pick one of them. Make sure that you repeat the code part string verbatim (including any whitespaces) in the resulting merged issue.
- The confidence value of a merged issue should be the highest confidence value among the issues being merged.

After your analysis, provide your response in JSON format matching this schema:

{{ response_schema | tojson(indent=2) }}

Do not output any other JSON, only the consolidated issues in the specified format:
```json
{
    "issues": [
        <list of consolidated issues>
    ]
}
```
[ROLE=ASSISTANT]
"""


def _get_deduplication_prompt(
    enabled_issue_codes: Iterable[IssueCode],
    generated_issues: str,
) -> str:
    # Sort issue codes to make the resulting prompts deterministic (for snapshot tests and LLM caching)
    sorted_issue_codes = sorted(enabled_issue_codes)
    formatted_guides = {
        code: format_issue_identification_guide_for_llm(
            ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE[code]
        )
        for code in sorted_issue_codes
    }

    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    jinja_template = env.from_string(DEDUPLICATION_PROMPT_TEMPLATE)

    prompt = jinja_template.render(
        {
            "guides": formatted_guides,
            "response_schema": GeneratedResponseSchema.model_json_schema(),
            "generated_issues": escape_prompt_markers(generated_issues),
        }
    )
    return prompt


def _convert_parsed_issues_to_combined_string(
    all_parsed_issues: Iterable[GeneratedIssueSchema],
) -> str:
    """Convert all parsed issues from all issue types to a combined string for the deduplication prompt."""
    combined_issues = []

    for issue in all_parsed_issues:
        issue_dict = issue.model_dump()
        combined_issues.append(issue_dict)

    return json.dumps({"issues": combined_issues}, indent=2)


def deduplicate_issues(
    issue_generator: Generator[
        GeneratedIssueSchema, None, IssueIdentificationDebugInfo
    ],
    config: VetConfig,
    enabled_issue_codes: Iterable[IssueCode],
) -> Generator[GeneratedIssueSchema, None, IssueIdentificationDebugInfo]:
    """
    Deduplicate issues from multiple issue identifiers.

    Args:
        issues: The issues to deduplicate.
        config: Settings
        enabled_issue_codes: The issue types used by the issue identifiers.

    Returns:
        A generator of deduplicated issues. Returns IssueIdentificationDebugInfo after the generator is exhausted.
    """

    # This current implementation is not streaming. Rather, we collect all issues, then send them to the LLM for deduplication all at once.
    # In the future, we can consider changing this into a streaming version that performs deduplication as issues come in.
    dedup_start = time.monotonic()
    logger.debug(
        "[TIMING] DEDUPLICATION: starting - collecting issues from upstream phases"
    )

    all_issues = []
    issue_generator_with_capture = ReturnCapturingGenerator(issue_generator)
    for issue in issue_generator_with_capture:
        all_issues.append(issue)
    issue_generator_debug_info = issue_generator_with_capture.return_value

    collect_elapsed = time.monotonic() - dedup_start
    logger.debug(
        "[TIMING] DEDUPLICATION: collected {num_issues} issues from upstream in {elapsed:.2f}s",
        num_issues=len(all_issues),
        elapsed=collect_elapsed,
    )

    # TODO: This is a bit hacky, since it breaks abstraction boundaries:
    #   We need to apply some special handling here around issue filtration.
    #   This will go away when in the future, we move the filtration step to after the deduplication step.
    #   However, we can't do that yet, because the filtration currently only works for certain issue types.
    #   For now, we make the following compromise:
    #   - We deduplicate only over issues that pass filtration.
    #     (The resulting deduplicated issues will implicitly be set to have passed filtration as well, as per default value of _passes_filtration)
    #   - Issues that didn't pass filtration will be yielded out unchanged.
    issues_passing_filtration = [
        issue for issue in all_issues if issue.passes_filtration
    ]
    issues_not_passing_filtration = [
        issue for issue in all_issues if not issue.passes_filtration
    ]

    if len(issues_passing_filtration) <= 1:
        # None or one issues that pass filtration: nothing to deduplicate, return early
        total_elapsed = time.monotonic() - dedup_start
        logger.debug(
            "[TIMING] DEDUPLICATION: skipped (<=1 issues passing filtration) in {elapsed:.2f}s",
            elapsed=total_elapsed,
        )
        for issue in all_issues:
            yield issue
        return issue_generator_debug_info

    language_model = build_language_model_from_config(
        config.language_model_generation_config
    )

    # As per above TODO, only deduplicate over issues that passed filtration
    combined_issues_string = _convert_parsed_issues_to_combined_string(
        issues_passing_filtration
    )
    prompt = _get_deduplication_prompt(enabled_issue_codes, combined_issues_string)

    llm_start = time.monotonic()
    logger.debug(
        "[TIMING] DEDUPLICATION: starting LLM call with {num_issues} issues passing filtration",
        num_issues=len(issues_passing_filtration),
    )
    costed_response = language_model.complete_with_usage_sync(
        prompt,
        params=LanguageModelGenerationParams(
            temperature=0.0, max_tokens=config.max_output_tokens
        ),
        is_caching_enabled=language_model.cache_path is not None,
    )

    llm_elapsed = time.monotonic() - llm_start
    response = only(costed_response.responses)
    invocation_info = extract_invocation_info_from_costed_response(costed_response)

    total_elapsed = time.monotonic() - dedup_start
    logger.debug(
        "[TIMING] DEDUPLICATION: completed in {total_elapsed:.2f}s (LLM call: {llm_elapsed:.2f}s)",
        total_elapsed=total_elapsed,
        llm_elapsed=llm_elapsed,
    )

    yield from generate_issues_from_response_texts(response_texts=(response.text,))

    # As per above TODO, now also yield out all issues that didn't pass filtration unchanged (these will keep their passes_filtration=False)
    for issue in issues_not_passing_filtration:
        yield issue

    deduplication_llm_responses = (
        LLMResponse(
            metadata=IssueIdentificationLLMResponseMetadata(
                agentic_phase=AgenticPhase.DEDUPLICATION,
                issue_type=None,
            ),
            raw_response=(response.text,),
            invocation_info=invocation_info,
        ),
    )

    augmented_debug_info = IssueIdentificationDebugInfo(
        llm_responses=issue_generator_debug_info.llm_responses
        + deduplication_llm_responses
    )

    return augmented_debug_info
