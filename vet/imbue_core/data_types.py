"""
Interfaces and data types for the issue identification system.

We foresee two basic kinds of issue identifiers:

    1. Heavily specialized ones.
        - Those would typically only check for a single well-defined issue.
        - The user only wants to know if a specific thing is wrong.
    2. General ones.
        - They would still have a certain focus but they would typically check for a broader range of issues.
        - We wouldn't know the whole range of possible issues in advance.
        - Here, the user asks for up to N most problematic issues of the given kind in a given scope.

Issue identifiers can either be created:
    - by implementing the IssueIdentifier protocol in an arbitrary way
    - or by leaning on a common LLM-based zero-shot classifier
        - This has the advantage of being more efficient.
        - We can ask for a (set of) score(s) on various metrics / error types for a list of scopes.
        - These computations can basically all be batched together into a single call to the LLM.
        - NOTE: as of writing this, this hasn't been implemented yet.

What follows is a list of possible issues we may eventually want to identify:


- docstrings / documentation / tests / constraints / validation
    - missing
    - outdated
    - ambiguous
    - poorly written / duplicated
    - conflicting
    - insufficient
- assumptions
    - unstated
    - violated
    - conflicting
- possible race condition
- overly complex code
- code in need of refactoring
- project layout in need of refactoring
- duplicated code
- brittle logic
- use of state (at all, where unnecessary, where needless)
- gross inefficiency
- caching (the presence of, at all)
- bad/confusing/unclear naming
- forbidden stylistic patterns (that cannot be caught by ratchets)
- poorly handled edge cases
- just plain ol bugs, overall correctness, etc
- missing test coverage (not line based, but more meaning based, esp around integration tests)
- disagreeing ensembles
- missing features / implementations / etc
- refactoring elements that were missed
- invocation outputs that seem suspect
- overly broad types
- misunderstanding the users mental model
- architectural flaws
- general critiques
- better alternatives
- reinvented wheels / places where some library or external service should have been used
- mutated globals / global state / imported globals
- any unnecessary complexity

There are also things we explicitly don't want to catch with this system:

- runtime errors (when running a main script or tests)
- most ratchet errors
- anything caught by an existing tool (typing, pylint, tests, etc)
- errors during the deployment process itself
- errors when building the image
- errors about packaging, installation, dependencies, etc
- errors collected from production

"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator

from vet.imbue_core.common import generate_id
from vet.imbue_core.pydantic_serialization import SerializableModel

# Define semantics for the normalized confidence and severity scores.
CONFIDENCE_CERTAINLY_FINE = (0.0, 0.2)
CONFIDENCE_RATHER_FINE = (0.2, 0.4)
CONFIDENCE_NOT_SURE = (0.4, 0.6)
CONFIDENCE_RATHER_PROBLEMATIC = (0.6, 0.8)
CONFIDENCE_CERTAINLY_PROBLEMATIC = (0.8, 1.0)


class ConfidenceScore(SerializableModel):
    """
    A score for the confidence in the issue / error detection.

    - The raw score is the score as output by the underlying model.
    - The normalized score is rescaled in such a way that the interval between 0 and 1 maps to the defined confidence levels.

    """

    raw: float
    normalized: float


class SeverityScore(SerializableModel):
    """
    A score for the severity of the issue / error.

    - The raw score is the score as potentially output by the underlying model.
    - The normalized score is rescaled in such a way that the interval between 0 and 1 maps to the defined severity levels.

    """

    raw: float
    normalized: float


class LineRange(SerializableModel):
    start: int
    end: int

    def __lt__(self, other: "LineRange") -> bool:
        if self.start != other.start:
            return self.start < other.start
        return self.end < other.end

    @classmethod
    def build_from_substring(
        cls, file_contents: str, substring: str
    ) -> tuple["LineRange", ...]:
        """
        Convert a substring in a file to a tuple of LineRange instances.

        Each LineRange instance corresponds to a single occurrence of the substring in the file.
        (Except when multiple occurences are on the same line, in which case only one LineRange is
        created to represent them).

        LineRanges are returned in the order they appear in the file.

        In case the substring can't be found, an empty tuple is returned.

        """

        line_ranges = set()
        offset_chars = 0
        offset_lines = 0
        while True:
            cut_contents = file_contents[offset_chars:]
            start_index = cut_contents.find(substring)
            if start_index == -1:
                break
            end_index = start_index + len(substring)
            line_start = offset_lines + cut_contents.count("\n", 0, start_index)
            line_end = offset_lines + cut_contents.count("\n", 0, end_index)
            offset_chars += end_index
            offset_lines = line_end
            line_ranges.add(LineRange(start=line_start, end=line_end))
        return tuple(sorted(line_ranges))


class AgenticPhase(StrEnum):
    """Phases of agentic analysis."""

    ISSUE_IDENTIFICATION = "issue_identification"
    COLLATION = "collation"
    FILTRATION = "filtration"
    DEDUPLICATION = "deduplication"


class AgentHarnessType(StrEnum):
    CLAUDE = "claude"
    CODEX = "codex"
    OPENCODE = "opencode"


class IssueIdentifierType(StrEnum):
    BATCHED_COMMIT_CHECK = "batched_commit_check"
    CORRECTNESS_COMMIT_CLASSIFIER = "correctness_commit_classifier"
    AGENTIC_ISSUE_IDENTIFIER = "agentic_issue_identifier"
    CONVERSATION_HISTORY_IDENTIFIER = "conversation_history_issue_identifier"


class IssueCode(StrEnum):
    """
    A code for the type of issue / error detected.

    The code can either correspond something very specific (e.g. "ambiguous_docstring")
    or to something more general (e.g. "function_implementation").

    The latter case would be used as an "umbrella" code in cases we don't know what exactly comes out of an issue verifier.

    """

    # Verifier-based.
    INCORRECT_FUNCTION_IMPLEMENTATION = "incorrect_function_implementation"

    # Batched file checks
    INEFFICIENT_CODE = "inefficient_code"
    BAD_NAMING = "bad_naming"
    POOR_DOCSTRING = "poor_docstring"
    RACE_CONDITION = "race_condition"
    HARDCODED_SECRET = "hardcoded_secret"
    DUPLICATE_CODE = "duplicate_code"
    UNUSED_CODE = "unused_code"
    COMMIT_MESSAGE_MISMATCH = "commit_message_mismatch"

    # Batched commit checks
    INCOMPLETE_INTEGRATION_WITH_EXISTING_CODE = (
        "incomplete_integration_with_existing_code"
    )
    DOCUMENTATION_IMPLEMENTATION_MISMATCH = "documentation_implementation_mismatch"
    USER_REQUEST_ARTIFACTS_LEFT_IN_CODE = "user_request_artifacts_left_in_code"
    POOR_NAMING = "poor_naming"
    REPETITIVE_OR_DUPLICATE_CODE = "repetitive_or_duplicate_code"
    REFACTORING_NEEDED = "refactoring_needed"
    TEST_COVERAGE = "test_coverage"
    RESOURCE_LEAKAGE = "resource_leakage"
    DEPENDENCY_MANAGEMENT = "dependency_management"
    INSECURE_CODE = "insecure_code"
    CORRECTNESS_SYNTAX_ISSUES = "correctness_syntax_issues"
    FAILS_SILENTLY = "fails_silently"
    INSTRUCTION_FILE_DISOBEYED = "instruction_file_disobeyed"
    ABSTRACTION_VIOLATION = "abstraction_violation"

    # Correctness commit classifier
    LOGIC_ERROR = "logic_error"
    RUNTIME_ERROR_RISK = "runtime_error_risk"
    INCORRECT_ALGORITHM = "incorrect_algorithm"
    ERROR_HANDLING_MISSING = "error_handling_missing"
    ASYNC_CORRECTNESS = "async_correctness"
    TYPE_SAFETY_VIOLATION = "type_safety_violation"

    # Conversation history identifier
    MISLEADING_BEHAVIOR = "misleading_behavior"
    INSTRUCTION_TO_SAVE = "instruction_to_save"

    # Github dataset, not yet implemented in commit checks
    MISMATCHED_CODE_PATTERNS = "mismatched_code_patterns"

    # Issue code for flagging suggested improvements or new features, as opposed to actual issues
    SUGGESTED_IMPROVEMENT = "suggested_improvement"

    # Catchall
    MISCELLANEOUS = "miscellaneous"
    ALL_CODE_ISSUES = "all_code_issues"

    # Deprecated
    _DEPRECATED_LLM_ARTIFACTS_LEFT_IN_CODE = "llm_artifacts_left_in_code"


def get_valid_issue_code_values() -> set[str]:
    return {code.value for code in IssueCode if not code.name.startswith("_DEPRECATED")}


class CustomGuideConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    prefix: str | None = None
    suffix: str | None = None
    replace: str | None = None

    @model_validator(mode="after")
    def validate_fields(self) -> "CustomGuideConfig":
        has_prefix_or_suffix = self.prefix is not None or self.suffix is not None
        has_replace = self.replace is not None
        if has_replace and has_prefix_or_suffix:
            raise ValueError(
                "'replace' cannot be used together with 'prefix' or 'suffix'"
            )
        if not has_replace and not has_prefix_or_suffix:
            raise ValueError(
                "At least one of 'prefix', 'suffix', or 'replace' must be set"
            )
        return self


class CustomGuidesConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    guides: dict[str, CustomGuideConfig] = Field(default_factory=dict)


class IssueLocation(SerializableModel):
    """A location in a file."""

    line_start: int
    line_end: int
    filename: str | None = None
    # The scope of the issue. Usually the qualified name of the function that the issue is located in.
    # If the issue is part of a class definition (and not limited to a particular method),
    # the name of the class. If the issue is at the global file level, None.
    scope: str | None = None


IssueID = str


class IdentifiedVerifyIssue(SerializableModel):
    """An identified code issue / error."""

    issue_id: IssueID | None = Field(default_factory=generate_id)
    code: IssueCode
    description: str
    severity_score: SeverityScore
    location: tuple[IssueLocation, ...] = Field(default_factory=tuple)
    confidence_score: ConfidenceScore | None = None
    fix: str | None = None
    violating_instruction: str | None = None
    violating_instruction_location: IssueLocation | None = None
    # TODO: remove these fields

    # An issue is fundamentally fixable if we can change the implementation to make the issue go away.
    # (An example of a non-fixable issue is a nonsensical commit message - changing the implementation doesn't help here.)
    # - iffv something is not fixable why would we want to report it?
    is_fixable: bool = True


class InvocationInfo(SerializableModel):
    """Information about an LLM invocation including token usage, timing, and cost. Populate whichever fields are available."""

    input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    total_input_tokens: int | None = None
    output_tokens: int | None = None
    duration_ms: float | None = None
    cost: float | None = None
    num_turns: int | None = None


class IssueIdentificationLLMResponseMetadata(SerializableModel):
    """Configuration metadata for LLM responses."""

    type: Literal[
        "IssueIdentificationLLMResponseMetadata", "IssueIdentificationLLMResponseConfig"
    ] = "IssueIdentificationLLMResponseMetadata"
    agentic_phase: AgenticPhase | None = None
    issue_type: IssueCode | None = None
    identifier_name: str | None = None
    issue_ids: tuple[IssueID] | None = None


class LLMResponse(SerializableModel):
    metadata: IssueIdentificationLLMResponseMetadata  # Make this a union if there are other types of LLM responses
    raw_response: tuple[str, ...]
    invocation_info: InvocationInfo | None = None

    # Deprecated fields
    config: IssueIdentificationLLMResponseMetadata | None = Field(
        default=None, deprecated=True
    )


class IssueIdentificationDebugInfo(SerializableModel):
    llm_responses: tuple[LLMResponse, ...]


class IssueIdentifierResult(SerializableModel):
    """Container for an identified issue along with the LLM responses that generated it."""

    issue: IdentifiedVerifyIssue
    passes_filtration: bool = True
