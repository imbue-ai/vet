import pytest
from syrupy.assertion import SnapshotAssertion

from vet.imbue_core.data_types import IssueCode
from vet.imbue_core.data_types import IssueIdentifierType
from vet.imbue_core.frozen_utils import FrozenDict
from vet.imbue_tools.get_conversation_history.input_data_types import ConversationInputs
from vet.imbue_tools.get_conversation_history.input_data_types import IdentifierInputs
from vet.imbue_tools.get_conversation_history.input_data_types import (
    IdentifierInputsMissingError,
)
from vet.imbue_tools.repo_utils.project_context import BaseProjectContext
from vet.imbue_tools.repo_utils.context_prefix import SubrepoContextWithFormattedContext
from vet.imbue_tools.types.vet_config import VetConfig
from vet.imbue_tools.types.vet_config import get_enabled_issue_codes
from vet.vet_types.chat_state import TextBlock
from vet.vet_types.ids import AssistantMessageID
from vet.vet_types.messages import AgentMessageSource
from vet.vet_types.messages import ChatInputUserMessage
from vet.vet_types.messages import LLMModel
from vet.vet_types.messages import ResponseBlockAgentMessage
from vet.issue_identifiers.base import IssueIdentifier
from vet.issue_identifiers.custom_guides import CustomGuideOverride
from vet.issue_identifiers.harnesses.conversation_single_prompt import (
    ConversationSinglePromptHarness,
)
from vet.issue_identifiers.identification_guides import (
    ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE,
)
from vet.issue_identifiers.identification_guides import IssueIdentificationGuide
from vet.issue_identifiers.identification_guides import build_merged_guides
from vet.issue_identifiers.registry import _build_identifiers
from vet.issue_identifiers.registry import _get_enabled_identifier_names


def test_to_required_inputs() -> None:
    harness = ConversationSinglePromptHarness()
    classifier = harness.make_issue_identifier(
        identification_guides=(ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE[IssueCode.MISLEADING_BEHAVIOR],)
    )

    # should support inputs where only the conversation history is present
    conversation_history_inputs = IdentifierInputs(
        maybe_conversation_history=(
            ChatInputUserMessage(
                text="fake content",
                model_name=LLMModel.CLAUDE_4_SONNET,
            ),
        )
    )
    cvi = classifier.to_required_inputs(conversation_history_inputs)
    assert isinstance(cvi, ConversationInputs)

    # and inputs where the conversation history and commit message are present
    conversation_history_and_commit_message_inputs = IdentifierInputs(
        maybe_conversation_history=(
            ResponseBlockAgentMessage(
                source=AgentMessageSource.AGENT,
                role="assistant",
                assistant_message_id=AssistantMessageID("fake_message_id"),
                content=(TextBlock(text="fake content"),),
            ),
        ),
        maybe_goal="test",
        maybe_diff="test",
    )
    cvi = classifier.to_required_inputs(conversation_history_and_commit_message_inputs)
    assert isinstance(cvi, ConversationInputs)
    assert cvi.maybe_goal == "test"
    assert cvi.maybe_diff == "test"

    # should not support inputs where the conversation history is absent
    commit_inputs = IdentifierInputs(maybe_goal="test", maybe_diff="test")
    with pytest.raises(IdentifierInputsMissingError):
        classifier.to_required_inputs(commit_inputs)
    file_inputs = IdentifierInputs(maybe_files=("test.py",))
    with pytest.raises(IdentifierInputsMissingError):
        classifier.to_required_inputs(file_inputs)
    no_inputs = IdentifierInputs()
    with pytest.raises(IdentifierInputsMissingError):
        classifier.to_required_inputs(no_inputs)


def _build_conversation_identifier(
    guides_by_code: dict[IssueCode, IssueIdentificationGuide] | None = None,
) -> IssueIdentifier:
    """Build the conversation identifier via the production path (_build_identifiers)."""
    config = VetConfig()
    if guides_by_code is None:
        guides_by_code = config.guides_by_code
    identifiers = _build_identifiers(
        _get_enabled_identifier_names(config),
        get_enabled_issue_codes(config),
        guides_by_code,
    )
    for name, identifier in identifiers:
        if IssueIdentifierType.CONVERSATION_HISTORY_IDENTIFIER.value in name:
            return identifier
    raise ValueError("Conversation identifier not found")


SNAPSHOT_PROJECT_CONTEXT = BaseProjectContext(
    file_contents_by_path=FrozenDict({"test.py": "print('hello')"}),
    cached_prompt_prefix="[ROLE=SYSTEM]\nSystem context here",
    instruction_context=SubrepoContextWithFormattedContext(
        repo_context_files=(),
        subrepo_context_strategy_label="docs",
        formatted_repo_context="Instruction context here",
    ),
)
SNAPSHOT_CONVERSATION_INPUTS = ConversationInputs(
    maybe_conversation_history=(
        ChatInputUserMessage(
            text="Please add a hello world function",
            model_name=LLMModel.CLAUDE_4_SONNET,
        ),
        ResponseBlockAgentMessage(
            source=AgentMessageSource.AGENT,
            role="assistant",
            assistant_message_id=AssistantMessageID("msg_001"),
            content=(TextBlock(text="I'll add a hello world function for you."),),
        ),
    ),
)


def test_prompt_snapshot(snapshot: SnapshotAssertion) -> None:
    """Snapshot the exact prompt sent to the LLM to catch unintended prompt regressions."""
    identifier = _build_conversation_identifier()
    prompt = identifier._get_prompt(SNAPSHOT_PROJECT_CONTEXT, VetConfig(), SNAPSHOT_CONVERSATION_INPUTS)
    assert prompt == snapshot


def test_prompt_snapshot_with_custom_guides(snapshot: SnapshotAssertion) -> None:
    """Snapshot prompt with custom guide overrides for conversation harness.

    Covers different override modes across conversation issue codes:
    - misleading_behavior: prefix + suffix combined
    - instruction_file_disobeyed: replace (fully replaces the default guide)
    - instruction_to_save: left as default (no override)
    """
    merged_guides = build_merged_guides(
        {
            IssueCode.MISLEADING_BEHAVIOR: CustomGuideOverride(
                issue_code=IssueCode.MISLEADING_BEHAVIOR,
                prefix="CUSTOM PREFIX: Pay close attention to claims about test results.",
                suffix="CUSTOM SUFFIX: Also flag any fabricated error messages.",
            ),
            IssueCode.INSTRUCTION_FILE_DISOBEYED: CustomGuideOverride(
                issue_code=IssueCode.INSTRUCTION_FILE_DISOBEYED,
                replace="CUSTOM REPLACEMENT: Check that the agent follows all instruction files exactly.",
            ),
        }
    )
    identifier = _build_conversation_identifier(guides_by_code=merged_guides)
    prompt = identifier._get_prompt(SNAPSHOT_PROJECT_CONTEXT, VetConfig(), SNAPSHOT_CONVERSATION_INPUTS)
    assert prompt == snapshot
