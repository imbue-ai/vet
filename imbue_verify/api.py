"""Public API for imbue_verify.

This module provides functions to identify issues in code changes. Issue identifiers are pieces of logic capable of finding issues in code.
By default, imbue_verify runs all registered issue identifiers and returns all found issues.
"""

from pathlib import Path

from loguru import logger

from imbue_core.data_types import IdentifiedVerifyIssue
from imbue_core.data_types import IssueIdentificationDebugInfo
from imbue_core.sculptor.state.messages import ConversationMessageUnion
from imbue_tools.get_conversation_history.get_conversation_history import ConversationLoadingError
from imbue_tools.get_conversation_history.input_data_types import IdentifierInputs
from imbue_tools.repo_utils.project_context import LazyProjectContext
from imbue_tools.repo_utils.project_context import ProjectContext
from imbue_tools.types.imbue_verify_config import ImbueVerifyConfig
from imbue_tools.util_prompts.goal_from_conversation import get_goal_from_conversation
from imbue_verify.issue_identifiers import registry
from imbue_verify.issue_identifiers.utils import ReturnCapturingGenerator
from imbue_verify.repo_utils import IMBUE_VERIFY_MAX_PROMPT_TOKENS
from imbue_verify.repo_utils import get_code_to_check


def get_issues_with_raw_responses(
    base_commit: str,
    diff: str,
    diff_no_binary: str,
    goal: str,
    config: ImbueVerifyConfig,
    repo_path: Path,
    conversation_history: tuple[ConversationMessageUnion, ...] | None = None,
) -> tuple[tuple[IdentifiedVerifyIssue, ...], IssueIdentificationDebugInfo, ProjectContext]:
    if not goal or not goal.strip():
        logger.info("No goal was provided, generating one from conversation history")
        # should be not None and not empty
        if conversation_history:
            try:
                # TODO: we use the imbue verify config here, but we may want to configure this separately
                goal = get_goal_from_conversation(conversation_history, config.language_model_generation_config)
                logger.info("Generated goal from conversation history: {}", goal)
            except Exception as e:
                raise ConversationLoadingError(
                    f"No goal was provided and generating one from conversation history failed: {e}"
                )
        else:
            # TODO: Consider which CLI options we should show this for (quiet, normal, verbose).
            logger.info("No goal or conversation history provided, only goal-independent identifiers will run")
            goal = ""

    lm_config = config.language_model_generation_config
    if diff_no_binary:
        diff_no_binary_tokens = lm_config.count_tokens(diff_no_binary)
    else:
        diff_no_binary_tokens = 0

    project_context = LazyProjectContext.build(
        base_commit,
        diff,
        language_model_name=lm_config.model_name,
        repo_path=repo_path,
        # This needs to account for the imbue_verify prompt, as well as the max_tokens output tokens.
        tokens_to_reserve=IMBUE_VERIFY_MAX_PROMPT_TOKENS + diff_no_binary_tokens + config.max_output_tokens,
        context_window=lm_config.get_max_context_length(),
        is_custom_model=lm_config.is_custom_model(),
    )

    identifier_inputs = IdentifierInputs(
        maybe_diff=diff_no_binary or None,
        maybe_goal=goal,
        maybe_conversation_history=conversation_history,
    )

    results_generator = registry.run(
        identifier_inputs=identifier_inputs,
        project_context=project_context,
        config=config,
    )

    issues = []
    results_generator_with_capture = ReturnCapturingGenerator(results_generator)
    for result in results_generator_with_capture:
        if result.passes_filtration:
            issues.append(result.issue)
    issue_identification_debug_info = results_generator_with_capture.return_value

    return tuple(issues), issue_identification_debug_info, project_context


def find_issues(
    repo_path: Path,
    relative_to: str,
    goal: str,
    config: ImbueVerifyConfig,
    conversation_history: tuple[ConversationMessageUnion, ...] | None = None,
) -> tuple[IdentifiedVerifyIssue, ...]:
    logger.info(
        "Finding issues in {repo_path} relative to commit hash {relative_to}",
        repo_path=repo_path,
        relative_to=relative_to,
    )

    base_commit, diff, diff_no_binary = get_code_to_check(relative_to, repo_path)
    if not diff.strip():
        logger.info(
            "No code changes detected in repo {repo_path} since the specified relative_to commit {relative_to}, skipping issue identification",
            repo_path=repo_path,
            relative_to=relative_to,
        )
        # No code changes detected since the specified relative_to commit, so no issues to find.
        return tuple()

    issues, _, _ = get_issues_with_raw_responses(
        base_commit=base_commit,
        diff=diff,
        diff_no_binary=diff_no_binary,
        goal=goal,
        config=config,
        repo_path=repo_path,
        conversation_history=conversation_history,
    )
    return issues
