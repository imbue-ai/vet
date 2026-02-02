"""
Registry of all the available issue identifiers with a `run` function for running them in an identification pipeline.
"""

from collections import defaultdict
from enum import StrEnum
from typing import Final
from typing import Generator
from typing import Iterable
from typing import TypeVar

from loguru import logger

from vet.imbue_core.agents.primitives.resource_limits import ensure_global_resource_limits
from vet.imbue_core.data_types import IssueCode
from vet.imbue_core.data_types import IssueIdentificationDebugInfo
from vet.imbue_core.data_types import IssueIdentificationLLMResponseMetadata
from vet.imbue_core.data_types import IssueIdentifierResult
from vet.imbue_core.data_types import IssueIdentifierType
from vet.imbue_tools.get_conversation_history.input_data_types import IdentifierInputs
from vet.imbue_tools.get_conversation_history.input_data_types import (
    IdentifierInputsMissingError,
)
from vet.imbue_tools.repo_utils.project_context import ProjectContext
from vet.imbue_tools.types.vet_config import VetConfig
from vet.imbue_tools.types.vet_config import get_enabled_issue_codes
from vet.issue_identifiers.agentic_issue_collation import (
    collate_issues_with_agent,
)
from vet.issue_identifiers.base import IssueIdentifier
from vet.issue_identifiers.common import GeneratedIssueSchema
from vet.issue_identifiers.common import convert_to_issue_identifier_result
from vet.issue_identifiers.harnesses.agentic import AgenticHarness
from vet.issue_identifiers.harnesses.base import IssueIdentifierHarness
from vet.issue_identifiers.harnesses.conversation_single_prompt import (
    ConversationSinglePromptHarness,
)
from vet.issue_identifiers.harnesses.single_prompt import SinglePromptHarness
from vet.issue_identifiers.identification_guides import (
    ISSUE_CODES_FOR_BATCHED_COMMIT_CHECK,
)
from vet.issue_identifiers.identification_guides import (
    ISSUE_CODES_FOR_CONVERSATION_HISTORY_CHECK,
)
from vet.issue_identifiers.identification_guides import (
    ISSUE_CODES_FOR_CORRECTNESS_CHECK,
)
from vet.issue_identifiers.identification_guides import (
    ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE,
)
from vet.issue_identifiers.issue_deduplication import deduplicate_issues
from vet.issue_identifiers.issue_evaluation import filter_issues
from vet.issue_identifiers.utils import ReturnCapturingGenerator
from vet.issue_identifiers.utils import multiplex_generators

# Issue identifier harnesses together with certain default lists of issue codes.
# This is intended as a transitionary structure to emulate the previous identifiers setup.
# Eventually, we'll update VetConfig to no longer enable/disable specific identifiers, but instead
# enable/disable harnesses and issue codes, and we'll pair up the enabled issue codes with the appropriate enabled
# harnesses automatically.
SINGLE_PROMPT_HARNESS = SinglePromptHarness()
CONVERSATION_SINGLE_PROMPT_HARNESS = ConversationSinglePromptHarness()
AGENTIC_HARNESS = AgenticHarness()
HARNESS_PRESETS: Final[list[tuple[IssueIdentifierType, IssueIdentifierHarness, tuple[IssueCode, ...]]]] = [
    (
        IssueIdentifierType.AGENTIC_ISSUE_IDENTIFIER,
        AGENTIC_HARNESS,
        ISSUE_CODES_FOR_BATCHED_COMMIT_CHECK + ISSUE_CODES_FOR_CORRECTNESS_CHECK,
    ),
    (
        IssueIdentifierType.BATCHED_COMMIT_CHECK,
        SINGLE_PROMPT_HARNESS,
        ISSUE_CODES_FOR_BATCHED_COMMIT_CHECK,
    ),
    (
        IssueIdentifierType.CONVERSATION_HISTORY_IDENTIFIER,
        CONVERSATION_SINGLE_PROMPT_HARNESS,
        ISSUE_CODES_FOR_CONVERSATION_HISTORY_CHECK,
    ),
    (
        IssueIdentifierType.CORRECTNESS_COMMIT_CLASSIFIER,
        SINGLE_PROMPT_HARNESS,
        ISSUE_CODES_FOR_CORRECTNESS_CHECK,
    ),
]


def get_all_valid_identifier_names() -> set[IssueIdentifierType]:
    return {name for name, _, _ in HARNESS_PRESETS}


EnumT = TypeVar("EnumT", bound=StrEnum)


def _convert_all_to_enum(
    enum_strs: Iterable[str], all_enum_strs: Iterable[str], enum_type: type[EnumT]
) -> tuple[EnumT]:
    results = []
    for enum_str in enum_strs:
        if enum_str not in all_enum_strs:
            raise ValueError(f"Bad config: unknown {enum_type.__name__} name: {enum_str}")
        results.append(enum_type(enum_str))
    return tuple(results)


def _get_enabled_identifier_names(
    config: VetConfig,
) -> set[IssueIdentifierType]:
    all_names = get_all_valid_identifier_names()
    explicitly_enabled = _convert_all_to_enum(config.enabled_identifiers or tuple(), all_names, IssueIdentifierType)
    explicitly_disabled = _convert_all_to_enum(config.disabled_identifiers or tuple(), all_names, IssueIdentifierType)
    enabled = set(explicitly_enabled) if len(explicitly_enabled) > 0 else all_names
    if len(explicitly_disabled) > 0:
        enabled = set(enabled) - set(explicitly_disabled)
    return enabled


def _build_identifiers(
    identifiers_to_build: set[IssueIdentifierType], enabled_issue_codes: set[IssueCode]
) -> list[tuple[str, IssueIdentifier]]:
    # Merge the enabled issue codes for each harness
    enabled_issue_codes_per_harness: defaultdict[IssueIdentifierHarness, set[IssueCode]] = defaultdict(set)
    combined_name_per_harness: defaultdict[IssueIdentifierHarness, list[str]] = defaultdict(list)

    for name, harness, default_issue_codes in HARNESS_PRESETS:
        if name in identifiers_to_build:
            enabled_issue_codes_for_harness = enabled_issue_codes & set(default_issue_codes)
            if enabled_issue_codes_for_harness:
                enabled_issue_codes_per_harness[harness].update(enabled_issue_codes_for_harness)
                combined_name_per_harness[harness].append(name.value)

    identifiers: list[tuple[str, IssueIdentifier]] = []
    for harness, issue_codes in enabled_issue_codes_per_harness.items():
        combined_name = "+".join(combined_name_per_harness[harness])
        identifiers.append(
            (
                combined_name,
                harness.make_issue_identifier(
                    identification_guides=tuple(ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE[code] for code in issue_codes)
                ),
            )
        )

    return identifiers


def _generate_with_name_in_debug_info(
    name: str,
    generator: Generator[GeneratedIssueSchema, None, IssueIdentificationDebugInfo],
) -> Generator[GeneratedIssueSchema, None, tuple[str, IssueIdentificationDebugInfo]]:
    generator_with_capture = ReturnCapturingGenerator(generator)
    for result in generator_with_capture:
        yield result
    return name, generator_with_capture.return_value


def _combine_issue_generator_debug_info(
    generator: Generator[GeneratedIssueSchema, None, tuple[tuple[str, IssueIdentificationDebugInfo], ...]],
) -> Generator[GeneratedIssueSchema, None, IssueIdentificationDebugInfo]:
    collected_debug_info: tuple[tuple[str, IssueIdentificationDebugInfo], ...] = (yield from generator)

    updated_llm_responses = []
    for identifier_name, debug_info in collected_debug_info:
        for response in debug_info.llm_responses:
            assert isinstance(response.metadata, IssueIdentificationLLMResponseMetadata)
            updated_response = response.evolve(response.ref().metadata.identifier_name, identifier_name)
            updated_llm_responses.append(updated_response)

    return IssueIdentificationDebugInfo(llm_responses=tuple(updated_llm_responses))


def run(
    identifier_inputs: IdentifierInputs,
    project_context: ProjectContext,
    config: VetConfig,
) -> Generator[IssueIdentifierResult, None, IssueIdentificationDebugInfo]:
    """
    Run all the registered and configured issue identifiers on the given inputs.
    """
    enabled_issue_codes = get_enabled_issue_codes(config)
    identifiers = _build_identifiers(_get_enabled_identifier_names(config), enabled_issue_codes)
    ensure_global_resource_limits(max_dollars=config.max_identifier_spend_dollars)

    issue_generators: list[Generator[GeneratedIssueSchema, None, tuple[str, IssueIdentificationDebugInfo]]] = []
    compatible_enabled_identifier_names: list[str] = []
    # The set of issue codes that can be detected by the compatible identifiers. A subset of enabled_issue_codes.
    detectable_issue_codes: set[IssueCode] = set()
    for identifier_name, identifier in identifiers:
        # 1. Identification
        try:
            inputs = identifier.to_required_inputs(identifier_inputs)
            identified_issues_generator = identifier.identify_issues(inputs, project_context, config)
            compatible_enabled_identifier_names.append(identifier_name)
            detectable_issue_codes.update(identifier.enabled_issue_codes)
        except IdentifierInputsMissingError as e:
            logger.debug(
                "skipping identifier {} because of missing inputs: {}",
                identifier_name,
                e,
            )
            continue

        # 2. Collation for agentic identifiers
        if identifier.requires_agentic_collation and config.enable_collation:
            try:
                collated_issues_generator = collate_issues_with_agent(
                    identified_issues_generator,
                    identifier_inputs,
                    project_context,
                    config,
                    identifier.enabled_issue_codes,
                )
            except IdentifierInputsMissingError as e:
                logger.warning(
                    "collate_issues_with_agent requires commit message and diff, skipping: {}",
                    e,
                )
                continue
        else:
            collated_issues_generator = identified_issues_generator

        # 3. Filtration
        if config.filter_issues:
            filtered_results_generator = filter_issues(
                collated_issues_generator,
                identifier_inputs,
                project_context,
                config,
                is_code_based_issue_generator=identifier.identifies_code_issues,
            )
        else:
            filtered_results_generator = collated_issues_generator

        issue_generators.append(_generate_with_name_in_debug_info(identifier_name, filtered_results_generator))

    logger.info(
        "Using the following issue identifiers compatible with the input: {}",
        ", ".join([n for n in compatible_enabled_identifier_names]),
    )

    multiplexed_generators = multiplex_generators(issue_generators, max_workers=config.max_identify_workers)
    multiplexed_generators_with_combined_debug_info = _combine_issue_generator_debug_info(multiplexed_generators)

    # 4. Deduplicate issues across all identifiers
    if config.enable_deduplication:
        deduplicated_generator = deduplicate_issues(
            multiplexed_generators_with_combined_debug_info,
            config,
            tuple(detectable_issue_codes),
        )
    else:
        deduplicated_generator = multiplexed_generators_with_combined_debug_info

    # Conversion from GeneratedIssueSchema to IssueIdentifierResult
    converted_issues_generator = convert_to_issue_identifier_result(
        deduplicated_generator, project_context, tuple(enabled_issue_codes)
    )

    # Yield out results
    debug_info = yield from converted_issues_generator

    return debug_info
