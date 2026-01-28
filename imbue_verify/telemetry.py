from datetime import datetime

from imbue_core.agents.configs import LanguageModelGenerationConfig
from imbue_core.sculptor.state.messages import ConversationMessageUnion
from imbue_tools.capabilities_data_logging.common import get_current_user_name
from imbue_tools.capabilities_data_logging.data_types import CommandType
from imbue_tools.capabilities_data_logging.data_types import ImbueVerifyEvent
from imbue_tools.capabilities_data_logging.data_types import LoggedFeatureType
from imbue_tools.repo_utils.context_prefix import SubrepoContext
from imbue_tools.repo_utils.context_prefix import SubrepoContextWithFormattedContext
from imbue_tools.types.imbue_verify_config import ImbueVerifyConfig


def prune_context(context: SubrepoContext | None) -> SubrepoContext | None:
    if isinstance(context, SubrepoContextWithFormattedContext):
        return SubrepoContext(
            repo_context_files=context.repo_context_files,
            subrepo_context_strategy_label=context.subrepo_context_strategy_label,
        )
    return context


# TODO quick and dirty "new" event distinguished only by feature_name. should add more actual event types
async def create_imbue_verify_exception_event(
    base_commit: str,
    diff: str,
    goal: str,
    config: ImbueVerifyConfig,
    exception_name: str | None = None,
    created_at: datetime | None = None,
) -> ImbueVerifyEvent:
    """
    Log the repo state and goal to a local file.
    """
    # TODO: we should really be passing in the generation config not relying on these defaults
    generation_config = LanguageModelGenerationConfig(model_name=config.language_model_generation_config.model_name)
    event = ImbueVerifyEvent(
        task_description=goal,
        feature_name=LoggedFeatureType.VERIFY_EXCEPTION,
        generation_config=generation_config,
        user_id=get_current_user_name(),
        organization_id="Imbue",
        git_hash=base_commit,
        diff=diff,
        command_type=CommandType.IMBUE_VERIFY,
        imbue_verify_config=config,
        exception_name=exception_name,
        # If created_at is provided, use it, otherwise use the current time as measured by the event's constructor.
        # pyre-fixme[6]: pyre can't check unpacking untyped dict
        **(dict(created_at=created_at) if created_at else {}),
    )
    return event


async def create_imbue_verify_issues_found_event(
    base_commit: str,
    diff: str,
    goal: str,
    config: ImbueVerifyConfig,
    created_at: datetime | None = None,
    git_url: str | None = None,
    subrepo_context: SubrepoContext | None = None,
    instruction_context: SubrepoContext | None = None,
    conversation_history: tuple[ConversationMessageUnion, ...] | None = None,
) -> ImbueVerifyEvent:
    """
    Log the repo state and goal to a local file.
    """
    # TODO: this is kind of hacky but we don't want to log the formatted context as well since it's a lot to log
    pruned_subrepo_context = prune_context(subrepo_context)
    pruned_instruction_context = prune_context(instruction_context)
    # TODO: we should really be passing in the generation config not relying on these defaults
    generation_config = LanguageModelGenerationConfig(model_name=config.language_model_generation_config.model_name)
    if git_url:
        assert "https://oauth2:" not in git_url, f"Expected no oauth2 in url, {git_url=}"

    event = ImbueVerifyEvent(
        task_description=goal,
        feature_name=LoggedFeatureType.COMMAND_RUN,
        # TODO: maybe this should actually become something like a CodeGenerationConfig since that also has info about the context
        generation_config=generation_config,
        user_id=get_current_user_name(),
        organization_id="Imbue",
        git_hash=base_commit,
        diff=diff,
        command_type=CommandType.IMBUE_VERIFY,
        git_url=git_url,
        subrepo_context=pruned_subrepo_context,
        instruction_context=pruned_instruction_context,
        conversation_history=conversation_history,
        imbue_verify_config=config,
        # If created_at is provided, use it, otherwise use the current time as measured by the event's constructor.
        # pyre-fixme[6]: pyre can't check unpacking untyped dict
        **(dict(created_at=created_at) if created_at else {}),
    )
    return event
