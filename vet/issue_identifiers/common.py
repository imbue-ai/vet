"""
Common components shared between issue identifiers.
"""

from pathlib import Path
from typing import Generator
from typing import Iterable

import jinja2
from loguru import logger
from pydantic import Field
from pydantic import PrivateAttr

from vet.imbue_core.agents.agent_api.api import get_agent_client
from vet.imbue_core.agents.agent_api.claude.data_types import ClaudeCodeOptions
from vet.imbue_core.agents.agent_api.codex.data_types import CodexOptions
from vet.imbue_core.agents.agent_api.data_types import AgentAssistantMessage
from vet.imbue_core.agents.agent_api.data_types import AgentMessage
from vet.imbue_core.agents.agent_api.data_types import AgentOptions
from vet.imbue_core.agents.agent_api.data_types import AgentResultMessage
from vet.imbue_core.agents.agent_api.data_types import AgentTextBlock
from vet.imbue_core.agents.agent_api.data_types import AgentToolName
from vet.imbue_core.agents.agent_api.data_types import READ_ONLY_TOOLS
from vet.imbue_core.agents.agent_api.opencode.data_types import OpenCodeOptions
from vet.imbue_core.agents.llm_apis.anthropic_api import AnthropicModelName
from vet.imbue_core.agents.llm_apis.anthropic_data_types import AnthropicCachingInfo
from vet.imbue_core.agents.llm_apis.data_types import CostedLanguageModelResponse
from vet.imbue_core.agents.llm_apis.openai_api import OpenAIModelName
from vet.imbue_core.async_monkey_patches import log_exception
from vet.imbue_core.data_types import AgentHarnessType
from vet.imbue_core.data_types import ConfidenceScore
from vet.imbue_core.data_types import IdentifiedVerifyIssue
from vet.imbue_core.data_types import InvocationInfo
from vet.imbue_core.data_types import IssueCode
from vet.imbue_core.data_types import IssueIdentificationDebugInfo
from vet.imbue_core.data_types import IssueIdentifierResult
from vet.imbue_core.data_types import IssueLocation
from vet.imbue_core.data_types import LineRange
from vet.imbue_core.data_types import SeverityScore
from vet.imbue_core.pydantic_serialization import SerializableModel
from vet.imbue_tools.llm_output_parsing.parse_model_json_response import ResponseParsingError
from vet.imbue_tools.llm_output_parsing.parse_model_json_response import parse_model_json_response
from vet.imbue_tools.repo_utils.project_context import ProjectContext
from vet.issue_identifiers.identification_guides import IssueIdentificationGuide
from vet.issue_identifiers.utils import ReturnCapturingGenerator


class GeneratedIssueSchema(SerializableModel):
    """Individual issue from LLM response."""

    issue_code: str = Field(description="Category of the issue")
    description: str = Field(description="Specific explanation of what's wrong and why it's incorrect")
    location: str | None = Field(default=None, description="File path where the issue occurs")
    code_part: str | None = Field(default=None, description="Specific code snippet that has the issue")
    # pyre doesn't like the way ints/floats implement ge/le
    severity: int = Field(description="Integer 1-5 (1=minor issue, 5=critical bug)", ge=1, le=5)  # pyre-ignore[6]
    confidence: float = Field(description="Confidence in this assessment", ge=0.0, le=1.0)  # pyre-ignore[6]

    # ----------------------------------------------------------------
    # Internal mutable fields used by the post-identification pipeline for tagging.
    # These fields are mutable, but "monotic", in the sense that they can only be populated once and never
    # be changed again after that.
    # These won't be populated by issue identifiers and are not shown to LLMs.
    # ----------------------------------------------------------------
    _passes_filtration: bool | None = PrivateAttr(default=None)

    @property
    def passes_filtration(self) -> bool:
        if self._passes_filtration is None:
            # Default to True if not set
            return True
        else:
            return self._passes_filtration

    def set_passes_filtration(self, passes: bool) -> None:
        assert self._passes_filtration is None, "passes_filtration can only be set once"
        self._passes_filtration = passes


class GeneratedResponseSchema(SerializableModel):
    """Complete response structure for issue identification."""

    issues: list[GeneratedIssueSchema] = Field(default_factory=list, description="List of identified issues")


def generate_issues_from_response_texts(
    response_texts: Iterable[str],
) -> Generator[GeneratedIssueSchema, None, None]:
    """Generate IssueIdentifierResult objects from LLM response text."""
    for response_text in response_texts:
        try:
            parsed_data = parse_model_json_response(response_text, GeneratedResponseSchema)
        except ResponseParsingError:
            logger.warning(f"Failed to parse response text: {response_text}")
            continue

        for raw_issue in parsed_data.issues:
            yield raw_issue


def line_ranges_to_issue_locations(line_ranges: Iterable[LineRange], file_path: str) -> tuple[IssueLocation, ...]:
    """Convert LineRange objects to IssueLocation objects."""
    return tuple(
        IssueLocation(
            line_start=line_range.start,
            line_end=line_range.end,
            filename=file_path,
        )
        for line_range in line_ranges
    )


def convert_generated_issue_to_identified_issue(
    issue_data: GeneratedIssueSchema,
    project_context: ProjectContext,
    enabled_issue_codes: tuple[IssueCode, ...],
) -> IdentifiedVerifyIssue | None:
    try:
        # Validate issue code
        issue_code = issue_data.issue_code
        if issue_code not in enabled_issue_codes:
            logger.error(
                "Got issue code '{issue_code}', skipping. Expected one of: {enabled_issue_codes}",
                issue_code=issue_code,
                enabled_issue_codes=enabled_issue_codes,
            )
            return None

        # Extract location and code part for line ranges
        line_ranges: tuple[LineRange, ...] = ()
        issue_location = issue_data.location
        try:
            issue_location_path = Path(issue_location) if issue_location else None
            if project_context.repo_path and issue_location_path and issue_location_path.is_absolute():
                # Make absolute path relative.
                # This will raise ValueError if issue_location_path is not under repo_path.
                repo_path = project_context.repo_path
                assert repo_path is not None
                issue_location_path = issue_location_path.relative_to(repo_path)
        except ValueError:
            issue_location_path = None
            logger.warning(f"Invalid location '{issue_location}', skipping line range detection.")
        issue_code_part = issue_data.code_part
        if issue_location_path and issue_code_part:
            contents = project_context.file_contents_by_path.get(issue_location_path.as_posix())
            if contents is not None:
                line_ranges = LineRange.build_from_substring(contents, issue_code_part)
                if not line_ranges:
                    logger.debug(
                        "Could not find code_part in file {location}: {code_part_repr}",
                        location=issue_location,
                        code_part_repr=repr(issue_code_part),
                    )
            else:
                logger.warning(f"Unknown location '{issue_location}', skipping line range detection.")

        # Convert severity (1-5) to normalized score (0-1)
        severity_normalized = (issue_data.severity - 1) / 4.0  # Map 1-5 to 0-1
        locations = line_ranges_to_issue_locations(
            line_ranges, issue_location_path.as_posix() if issue_location_path else ""
        )
        return IdentifiedVerifyIssue(
            code=IssueCode(issue_data.issue_code),
            description=issue_data.description,
            severity_score=SeverityScore(raw=issue_data.severity, normalized=severity_normalized),
            confidence_score=ConfidenceScore(raw=issue_data.confidence, normalized=issue_data.confidence),
            location=locations,
        )

    except (ValueError, KeyError, TypeError) as e:
        log_exception(
            e,
            "Error processing issue data: {issue_data}, skipping",
            issue_data=issue_data,
        )
        return None


def convert_to_issue_identifier_result(
    generator: Generator[GeneratedIssueSchema, None, IssueIdentificationDebugInfo],
    project_context: ProjectContext,
    enabled_issue_codes: tuple[IssueCode, ...],
) -> Generator[IssueIdentifierResult, None, IssueIdentificationDebugInfo]:
    """Convert a generator of GeneratedIssueSchema to IssueIdentifierResult."""
    generator_with_capture = ReturnCapturingGenerator(generator)
    for issue_data in generator_with_capture:
        issue = convert_generated_issue_to_identified_issue(
            issue_data=issue_data,
            project_context=project_context,
            enabled_issue_codes=enabled_issue_codes,
        )
        if issue:
            yield IssueIdentifierResult(issue=issue, passes_filtration=issue_data.passes_filtration)

    return generator_with_capture.return_value


_ANTHROPIC_MODEL_NAMES = {m.value for m in AnthropicModelName}
_OPENAI_MODEL_NAMES = {m.value for m in OpenAIModelName}
_DEFAULT_CODEX_MODEL = "gpt-5.2-codex"
_DEFAULT_CLAUDE_MODEL = AnthropicModelName.CLAUDE_4_6_OPUS


def get_agent_options(cwd: Path | None, model_name: str, agent_harness_type: AgentHarnessType) -> AgentOptions:
    # NOTE: This if/else is intentionally simple. We're unlikely to support many harness types,
    # but if we do, this should be refactored into a registry or factory pattern.
    if agent_harness_type == AgentHarnessType.CODEX:
        if model_name in _ANTHROPIC_MODEL_NAMES:
            logger.debug(
                "Config model_name {config_model_name} is an Anthropic model, using default Codex model ({model_name}).",
                config_model_name=model_name,
                model_name=_DEFAULT_CODEX_MODEL,
            )
            model_name = _DEFAULT_CODEX_MODEL
        return CodexOptions(
            cwd=cwd,
            model=model_name,
            sandbox_mode="read-only",
        )
    if agent_harness_type == AgentHarnessType.OPENCODE:
        # OpenCode uses provider/model format (e.g. "anthropic/claude-opus-4-6").
        # Translate known vet model names to OpenCode format, or let OpenCode
        # use its configured default if the model name isn't recognized.
        opencode_model: str | None = None
        if model_name in _ANTHROPIC_MODEL_NAMES:
            opencode_model = f"anthropic/{model_name}"
        elif model_name in _OPENAI_MODEL_NAMES:
            opencode_model = f"openai/{model_name}"
        else:
            # Unknown model — pass through as-is and let OpenCode resolve it.
            # If it's already in provider/model format, it will work directly.
            opencode_model = model_name
        return OpenCodeOptions(
            cwd=cwd,
            model=opencode_model,
        )
    if model_name in _OPENAI_MODEL_NAMES:
        logger.debug(
            "Config model_name {config_model_name} is an OpenAI model, using default Claude model ({model_name}).",
            config_model_name=model_name,
            model_name=_DEFAULT_CLAUDE_MODEL,
        )
        model_name = _DEFAULT_CLAUDE_MODEL
    elif model_name not in _ANTHROPIC_MODEL_NAMES:
        logger.warning(
            "Config model_name {config_model_name} is not a valid Anthropic model, using default ({model_name}).",
            config_model_name=model_name,
            model_name=_DEFAULT_CLAUDE_MODEL,
        )
        model_name = _DEFAULT_CLAUDE_MODEL
    return ClaudeCodeOptions(
        cwd=cwd,
        permission_mode="dontAsk",
        allowed_tools=list(READ_ONLY_TOOLS) + [AgentToolName.BASH],
        model=model_name,
    )


def generate_response_from_agent(prompt: str, options: AgentOptions) -> tuple[str, list[AgentMessage]] | None:
    messages = []
    assistant_messages = []
    result_message = None
    try:
        with get_agent_client(options=options) as client:
            for message in client.process_query(prompt):
                messages.append(message)
                if isinstance(message, AgentAssistantMessage):
                    assistant_messages.append(message)
                elif isinstance(message, AgentResultMessage):
                    result_message = message
    except Exception as e:
        log_exception(e, "Agent API call failed")
        return None

    # Try to get response from result message first
    response_text = ""
    if result_message and result_message.result:
        response_text = result_message.result

    # If no result message, concatenate assistant messages
    if not response_text and assistant_messages:
        for message in assistant_messages:
            for content_block in message.content:
                if isinstance(content_block, AgentTextBlock):
                    response_text += content_block.text.strip() + "\n"

    return response_text, messages


def extract_invocation_info_from_costed_response(
    response: CostedLanguageModelResponse,
) -> InvocationInfo:
    usage = response.usage

    cache_creation_tokens = None
    cache_read_tokens = None

    if usage.caching_info is not None:
        caching_info = usage.caching_info
        cache_read_tokens = caching_info.read_from_cache

        if caching_info.provider_specific_data is not None:
            if isinstance(caching_info.provider_specific_data, AnthropicCachingInfo):
                cache_creation_tokens = (
                    caching_info.provider_specific_data.written_5m + caching_info.provider_specific_data.written_1h
                )
            else:
                logger.debug(
                    "Not recording caching info for provider specific data type {}",
                    type(caching_info.provider_specific_data),
                )

    return InvocationInfo(
        input_tokens=usage.prompt_tokens_used,
        cache_creation_input_tokens=cache_creation_tokens,
        cache_read_input_tokens=cache_read_tokens,
        total_input_tokens=usage.prompt_tokens_used,
        output_tokens=usage.completion_tokens_used,
        cost=usage.dollars_used,
    )


def extract_invocation_info_from_messages(
    messages: list[AgentMessage],
) -> InvocationInfo:
    """Extract invocation information from Agent messages."""
    for message in messages:
        if isinstance(message, AgentResultMessage):
            total_input_tokens = None
            usage = message.usage
            if usage:
                input_tokens = usage.input_tokens
                cached_tokens = usage.cached_tokens
                output_tokens = usage.output_tokens
            else:
                input_tokens = None
                cached_tokens = None
                output_tokens = None
            if usage and input_tokens is not None and cached_tokens is not None:
                total_input_tokens = input_tokens + cached_tokens
            return InvocationInfo(
                input_tokens=input_tokens,
                cache_creation_input_tokens=None,
                cache_read_input_tokens=cached_tokens,
                total_input_tokens=total_input_tokens,
                output_tokens=output_tokens,
                duration_ms=message.duration_ms,
                cost=usage.total_cost_usd if usage else None,
                num_turns=message.num_turns,
            )
    return InvocationInfo()


_ISSUE_IDENTIFICATION_LLM_FORMAT = """
Guidelines:{% filter indent(width=4) %}
{{ guide }}{% endfilter %}
{%- if examples %}
Examples:
{%- for example in examples %}
    - {{ example }}
{%- endfor %}
{%- endif -%}
{%- if exceptions %}
Exceptions:
{%- for exception in exceptions %}
    - {{ exception }}
{%- endfor %}
{%- endif -%}
"""


def format_issue_identification_guide_for_llm(guide: IssueIdentificationGuide) -> str:
    formatted_guide = jinja2.Template(_ISSUE_IDENTIFICATION_LLM_FORMAT).render(
        guide=guide.guide, examples=guide.examples, exceptions=guide.exceptions
    )

    return formatted_guide.strip()
