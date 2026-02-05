from pathlib import Path

from vet.imbue_core.agents.configs import LanguageModelGenerationConfig
from vet.imbue_core.agents.llm_apis.anthropic_api import AnthropicModelName
from vet.imbue_core.data_types import IssueCode
from vet.imbue_core.pydantic_serialization import SerializableModel

DEFAULT_CONFIDENCE_THRESHOLD = 0.8


class VetConfig(SerializableModel):
    """Configuration for the vet system."""

    # If none, all registered identifiers are used.
    # Otherwise, only the identifiers in this tuple are used.
    enabled_identifiers: tuple[str, ...] | None = None

    # Issue identifiers that are disabled are never used.
    disabled_identifiers: tuple[str, ...] | None = None

    # Similar to the above, but for reporting specific types of issues.
    # (Use the values from the vet.data_types.IssueCode enum.)
    enabled_issue_codes: tuple[IssueCode, ...] | None = None
    disabled_issue_codes: tuple[IssueCode, ...] | None = ()

    # Todo: Different models for different issue identifiers
    language_model_generation_config: LanguageModelGenerationConfig = LanguageModelGenerationConfig(
        model_name=AnthropicModelName.CLAUDE_4_6_OPUS
    )
    max_identifier_spend_dollars: float = 5.0
    max_output_tokens: int = 20000
    enable_parallel_agentic_issue_identification: bool = False
    max_identify_workers: int | None = None
    temperature: float = 0.5

    # If True, apply an additional LLM-based filtering stage, where each identified issue is evaluated
    # according to a number of quality criteria. Only issues that pass the evaluation are returned.
    filter_issues: bool = True
    filter_issues_through_llm_evaluator: bool = True
    filter_issues_below_confidence: float | None = DEFAULT_CONFIDENCE_THRESHOLD

    enable_deduplication: bool = True
    enable_collation: bool = True

    # If True, we attempt to cache the full prompts including specific inputs with the LLM provider.
    # There can be an additional cost for such a cache write, but it can help save cost in evaluation
    # contexts (such as black_box_evals) where the same inputs are being evaluated multiple times.
    cache_full_prompt: bool = False

    @classmethod
    def build(
        cls,
        language_model_name: str | None = None,
        language_model_cache_path: Path | None = None,
        enabled_identifiers: tuple[str, ...] | None = None,
        enable_parallel_agentic_issue_identification: bool = False,
        max_identify_workers: int | None = None,
        filter_issues: bool = True,
        filter_issues_below_confidence: float | None = DEFAULT_CONFIDENCE_THRESHOLD,
        enable_deduplication: bool = True,
        enable_collation: bool = True,
        enabled_issue_codes: tuple[IssueCode, ...] | None = None,
        temperature: float = 0.5,
        retry_jitter_factor: float = 0.0,
        cache_full_prompt: bool = False,
    ) -> "VetConfig":
        if not language_model_name:
            language_model_name = AnthropicModelName.CLAUDE_4_6_OPUS
        language_model_generation_config = LanguageModelGenerationConfig(
            model_name=language_model_name,
            cache_path=language_model_cache_path,
            retry_jitter_factor=retry_jitter_factor,
        )
        return cls(
            language_model_generation_config=language_model_generation_config,
            enabled_identifiers=enabled_identifiers,
            enable_parallel_agentic_issue_identification=enable_parallel_agentic_issue_identification,
            max_identify_workers=max_identify_workers,
            filter_issues=filter_issues,
            filter_issues_below_confidence=filter_issues_below_confidence,
            enable_deduplication=enable_deduplication,
            enable_collation=enable_collation,
            enabled_issue_codes=enabled_issue_codes,
            temperature=temperature,
            cache_full_prompt=cache_full_prompt,
        )


def get_enabled_issue_codes(config: VetConfig) -> set[IssueCode]:
    all_issue_code_values = {item.value for item in IssueCode}
    explicitly_enabled = config.enabled_issue_codes or tuple()
    explicitly_disabled = config.disabled_issue_codes or tuple()
    for code in explicitly_enabled + explicitly_disabled:
        if code not in all_issue_code_values:
            raise ValueError(f"Bad config: unknown issue code: {code}")
    possibly_enabled_values = set(explicitly_enabled) if len(explicitly_enabled) > 0 else set(v for v in IssueCode)
    disabled_values = set(explicitly_disabled)
    return possibly_enabled_values - disabled_values
