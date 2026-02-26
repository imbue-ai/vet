"""
Agentic harness that checks a given diff for issues using coding agents with tools.
"""

import concurrent.futures
import json
from concurrent.futures import ThreadPoolExecutor
from functools import cached_property
from typing import Any
from typing import Generator

import jinja2
from loguru import logger

from vet.imbue_core.agents.agent_api.data_types import AgentMessage
from vet.imbue_core.agents.agent_api.data_types import AgentOptions
from vet.imbue_core.agents.agent_api.errors import AgentAPIError
from vet.imbue_core.async_monkey_patches import log_exception
from vet.imbue_core.data_types import AgenticPhase
from vet.imbue_core.data_types import IssueCode
from vet.imbue_core.data_types import IssueIdentificationDebugInfo
from vet.imbue_core.data_types import IssueIdentificationLLMResponseMetadata
from vet.imbue_core.data_types import LLMResponse
from vet.imbue_tools.get_conversation_history.input_data_types import CommitInputs
from vet.imbue_tools.repo_utils.context_utils import escape_prompt_markers
from vet.imbue_tools.repo_utils.project_context import ProjectContext
from vet.imbue_tools.types.vet_config import VetConfig
from vet.issue_identifiers.base import IssueIdentifier
from vet.issue_identifiers.common import GeneratedIssueSchema
from vet.issue_identifiers.common import GeneratedResponseSchema
from vet.issue_identifiers.common import extract_invocation_info_from_messages
from vet.issue_identifiers.common import format_issue_identification_guide_for_llm
from vet.issue_identifiers.common import generate_issues_from_response_texts
from vet.issue_identifiers.common import generate_response_from_agent
from vet.issue_identifiers.common import get_agent_options
from vet.issue_identifiers.harnesses.base import IssueIdentifierHarness
from vet.issue_identifiers.identification_guides import IssueIdentificationGuide

PROMPT_TEMPLATE = """You are analyzing a code repository for potential issues. The repository files are available in {{ repo_path }}.

Assume that a user requested work to be done and a programmer delivered the diff below.
The changes from the diff are present in the codebase but are not yet committed.

### User request ###
{% filter indent(width=2) %}
{{ commit_message }}
{% endfilter %}

### Diff (lines starting with `-` indicate removed code, and lines starting with `+` indicate added code) ###
{% filter indent(width=2) %}
{{ unified_diff }}
{% endfilter %}
###

Your task is to help verify the quality of the diff.
We care only about specific categories of important issues.
The rubric below outlines these categories of important issues, and contains guidelines and examples to correctly identify them:
{% for issue_code, guide in guides.items() %}
---
**{{ issue_code }}**:
{{ guide }}
{% endfor %}
---

Use your standard tools to explore the repository and analyze the code thoroughly.
Look at the additional guidance section below for more details on how to find issues.

After your analysis, provide your response in JSON format matching this schema:

{{ response_schema | tojson(indent=2) }}

For each issue found, provide:
- issue_code: Category from the rubric above
- description: Specific explanation of the issue
- (if applicable) location: File path where the issue occurs (relative to {{ repo_path }})
- (if applicable) code_part: Specific code snippet that has the issue. Your code snippet should be the exact same as the original code including whitespace.
- severity: Integer 1-5 (1=minor, 5=critical)
- confidence: Float 0.0-1.0 indicating your confidence

Your response should look like:
```json
{
    "issues": [
        <list of issues>
    ]
}
```

If no issues are found, return: ```json{"issues": []}```

Focus on real issues that impact code quality, correctness, or maintainability.
You must not return issues that were already present in the code or issues that are fixed by the diff.
You must only return issues that were introduced by the diff.
Do not report duplicate issues with the same or equivalent descriptions.

### Additional Guidance for Finding Issues ###
You should use a Task tool to create a parallel task for each issue type in the rubric.
You should pass along the exact issue type definition with all details to the task.
Once all the Tasks have completed you can collate their results.
You should pass along any relevant information from the guidance below to the task.
Here is a non-exhaustive list of things that you can do using your tools within the task to find issues:
{% for issue_code, guidance in additional_guidance.items() %}
---
**{{ issue_code }}**:
{{ guidance }}
{% endfor %}
---
Note that this is just guidance on how to find issues, please refer to the rubric for the types of issues to find.
"""

ISSUE_TYPE_PROMPT_TEMPLATE = """You are analyzing a code repository for potential issues of type {{ issue_type }}. The repository files are available in {{ repo_path }}.

Assume that a user requested work to be done and a programmer delivered the diff below.
The changes from the diff are present in the codebase but are not yet committed.

### User request ###
{% filter indent(width=2) %}
{{ commit_message }}
{% endfilter %}

### Diff (lines starting with `-` indicate removed code, and lines starting with `+` indicate added code) ###
{% filter indent(width=2) %}
{{ unified_diff }}
{% endfilter %}
###

Your task is to help verify the quality of the diff.
Here is the definition of the issue type you are looking for:
**{{ issue_type }}**:
{{ guide }}

Use your standard tools to explore the repository and analyze the code thoroughly.
ONLY look for issues related to {{ issue_type }}.
Do NOT modify any files - this is read-only analysis.

After your analysis, provide your response in JSON format matching this schema:

{{ response_schema | tojson(indent=2) }}

For each issue found, provide:
- issue_code: Category from the rubric above
- description: Specific explanation of the issue
- (if applicable) location: File path where the issue occurs (relative to {{ repo_path }})
- (if applicable) code_part: Specific code snippet that has the issue. Your code snippet should be the exact same as the original code including whitespace.
- severity: Integer 1-5 (1=minor, 5=critical)
- confidence: Float 0.0-1.0 indicating your confidence

Your response should look like:
```json
{
    "issues": [
        <list of issues>
    ]
}
```

If no issues of this type are found, return: ```json{"issues": []}```
You must not return issues that were already present in the code or issues that are fixed by the diff.
You must only return issues that were introduced by the diff.
Do not report duplicate issues with the same or equivalent descriptions.
"""


ResponseText = str


def _generate_issues_worker(
    issue_code: IssueCode,
    prompt: str,
    options: AgentOptions,
) -> tuple[IssueCode, ResponseText, list[AgentMessage]] | None:
    issue_result = generate_response_from_agent(prompt, options)
    if issue_result is None:
        return None
    return issue_code, issue_result[0], issue_result[1]


class _AgenticIssueIdentifier(IssueIdentifier[CommitInputs]):
    _identification_guides: tuple[IssueIdentificationGuide, ...]

    def __init__(self, identification_guides: tuple[IssueIdentificationGuide, ...]) -> None:
        assert len(identification_guides) > 0, "At least one identification guide must be provided"
        self._identification_guides = identification_guides

    @cached_property
    def _response_schema(self) -> dict[str, Any]:
        return GeneratedResponseSchema.model_json_schema()

    def _get_prompt(
        self,
        project_context: ProjectContext,
        config: VetConfig,  # unused
        identifier_inputs: CommitInputs,
    ) -> str:
        env = jinja2.Environment(undefined=jinja2.StrictUndefined)
        jinja_template = env.from_string(PROMPT_TEMPLATE)
        additional_guidance_by_issue_code = {
            guide.issue_code: guide.additional_guide_for_agent for guide in self._identification_guides
        }

        formatted_guides = {
            guide.issue_code: format_issue_identification_guide_for_llm(guide) for guide in self._identification_guides
        }

        prompt = jinja_template.render(
            {
                "repo_path": project_context.repo_path,
                "commit_message": escape_prompt_markers(identifier_inputs.goal),
                "unified_diff": escape_prompt_markers(identifier_inputs.diff),
                "guides": formatted_guides,
                "response_schema": self._response_schema,
                "additional_guidance": additional_guidance_by_issue_code,
            }
        )
        return prompt

    def _get_prompt_for_issue_type(
        self,
        project_context: ProjectContext,
        identifier_inputs: CommitInputs,
        guide: IssueIdentificationGuide,
    ) -> str:
        env = jinja2.Environment(undefined=jinja2.StrictUndefined)
        jinja_template = env.from_string(ISSUE_TYPE_PROMPT_TEMPLATE)

        formatted_guide = format_issue_identification_guide_for_llm(guide)

        prompt = jinja_template.render(
            {
                "repo_path": project_context.repo_path,
                "commit_message": escape_prompt_markers(identifier_inputs.goal),
                "unified_diff": escape_prompt_markers(identifier_inputs.diff),
                "guide": formatted_guide,
                "response_schema": self._response_schema,
                "issue_type": guide.issue_code,
            }
        )
        return prompt

    def identify_issues(
        self,
        identifier_inputs: CommitInputs,
        project_context: ProjectContext,
        config: VetConfig,
    ) -> Generator[GeneratedIssueSchema, None, IssueIdentificationDebugInfo]:
        assert project_context.repo_path is not None, "Project context must have a valid repo_path, got None"

        options = get_agent_options(
            cwd=project_context.repo_path,
            model_name=config.agent_model_name,
            agent_harness_type=config.agent_harness_type,
        )

        if config.enable_parallel_agentic_issue_identification:
            llm_responses = []

            issue_prompts = [
                (
                    guide.issue_code,
                    self._get_prompt_for_issue_type(project_context, identifier_inputs, guide),
                )
                for guide in self._identification_guides
            ]
            with ThreadPoolExecutor(max_workers=config.max_identify_workers) as executor:
                tasks = [
                    executor.submit(_generate_issues_worker, issue_code, prompt, options)
                    for issue_code, prompt in issue_prompts
                ]

                for task in concurrent.futures.as_completed(tasks):
                    try:
                        result = task.result()
                    except AgentAPIError:
                        raise
                    except Exception as e:
                        log_exception(e, "Error processing issue type: {e}", e=e)
                        continue

                    if result is None:
                        continue

                    issue_code, issue_type_response_text, messages = result

                    yield from generate_issues_from_response_texts(response_texts=(issue_type_response_text,))

                    message_dumps = tuple(json.dumps(message.model_dump()) for message in messages)
                    invocation_info = extract_invocation_info_from_messages(messages)

                    llm_responses.append(
                        LLMResponse(
                            metadata=IssueIdentificationLLMResponseMetadata(
                                agentic_phase=AgenticPhase.ISSUE_IDENTIFICATION,
                                issue_type=issue_code,
                            ),
                            raw_response=message_dumps,
                            invocation_info=invocation_info,
                        )
                    )

            return IssueIdentificationDebugInfo(llm_responses=tuple(llm_responses))
        else:
            prompt = self._get_prompt(project_context, config, identifier_inputs)
            agent_response = generate_response_from_agent(prompt, options)
            if agent_response is None:
                raise RuntimeError(
                    "Agentic issue identification failed: no response received from agent CLI."
                    " Re-run with --verbose for details."
                )
            response_text, messages = agent_response

            message_dumps = tuple(json.dumps(message.model_dump()) for message in messages)
            invocation_info = extract_invocation_info_from_messages(messages)

            llm_responses = [
                LLMResponse(
                    metadata=IssueIdentificationLLMResponseMetadata(
                        agentic_phase=AgenticPhase.ISSUE_IDENTIFICATION,
                        issue_type=None,
                    ),
                    raw_response=message_dumps,
                    invocation_info=invocation_info,
                )
            ]

            yield from generate_issues_from_response_texts(response_texts=(response_text,))

            return IssueIdentificationDebugInfo(llm_responses=tuple(llm_responses))

    def input_type(self) -> type[CommitInputs]:
        return CommitInputs

    @property
    def enabled_issue_codes(self) -> tuple[IssueCode, ...]:
        return tuple(guide.issue_code for guide in self._identification_guides)

    @property
    def requires_agentic_collation(self) -> bool:
        return True

    @property
    def identifies_code_issues(self) -> bool:
        return True


class AgenticHarness(IssueIdentifierHarness[CommitInputs]):
    def make_issue_identifier(
        self, identification_guides: tuple[IssueIdentificationGuide, ...]
    ) -> IssueIdentifier[CommitInputs]:
        return _AgenticIssueIdentifier(identification_guides=identification_guides)
