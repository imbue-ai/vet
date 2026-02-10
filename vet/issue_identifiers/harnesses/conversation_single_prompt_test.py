from unittest import mock

import pytest
from pydantic import Field
from syrupy.assertion import SnapshotAssertion

from vet.imbue_core.agents.llm_apis.data_types import CostedLanguageModelResponse
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelGenerationParams
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelResponseUsage
from vet.imbue_core.agents.llm_apis.data_types import LanguageModelResponseWithLogits
from vet.imbue_core.agents.llm_apis.data_types import ResponseStopReason
from vet.imbue_core.agents.llm_apis.mock_api import LanguageModelMock
from vet.imbue_core.data_types import IssueCode
from vet.imbue_core.frozen_utils import FrozenDict
from vet.imbue_tools.get_conversation_history.input_data_types import ConversationInputs
from vet.imbue_tools.get_conversation_history.input_data_types import IdentifierInputs
from vet.imbue_tools.get_conversation_history.input_data_types import (
    IdentifierInputsMissingError,
)
from vet.imbue_tools.repo_utils.project_context import BaseProjectContext
from vet.imbue_tools.repo_utils.context_prefix import SubrepoContextWithFormattedContext
from vet.imbue_tools.types.vet_config import VetConfig
from vet.vet_types.chat_state import TextBlock
from vet.vet_types.ids import AssistantMessageID
from vet.vet_types.messages import AgentMessageSource
from vet.vet_types.messages import ChatInputUserMessage
from vet.vet_types.messages import LLMModel
from vet.vet_types.messages import ResponseBlockAgentMessage
from vet.issue_identifiers.custom_guides import CustomGuideOverride
from vet.issue_identifiers.harnesses.conversation_single_prompt import (
    ConversationSinglePromptHarness,
)
from vet.issue_identifiers.identification_guides import (
    ISSUE_CODES_FOR_CONVERSATION_HISTORY_CHECK,
)
from vet.issue_identifiers.identification_guides import (
    ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE,
)
from vet.issue_identifiers.identification_guides import build_merged_guides


class ConversationSinglePromptHarnessMock(LanguageModelMock):
    """Mock language model for testing ConversationSinglePromptHarness."""

    response_text: str = ""
    captured_prompts: list[str] = Field(default_factory=list)

    def complete_with_usage_sync(
        self,
        prompt: str,
        params: LanguageModelGenerationParams,
        is_caching_enabled: bool = True,
    ) -> CostedLanguageModelResponse:
        self.captured_prompts.append(prompt)
        self.stats.complete_calls += 1
        response = LanguageModelResponseWithLogits(
            text=self.response_text,
            token_count=len(self.response_text.split()),
            stop_reason=ResponseStopReason.END_TURN,
            network_failure_count=0,
            token_probabilities=self._get_token_probabilities(self.response_text),
        )
        usage = LanguageModelResponseUsage(
            prompt_tokens_used=100,
            completion_tokens_used=50,
            dollars_used=0.001,
            caching_info=None,
        )
        return CostedLanguageModelResponse(usage=usage, responses=(response,))


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


def test_prompt_snapshot(snapshot: SnapshotAssertion) -> None:
    """Snapshot the exact prompt sent to the LLM to catch unintended prompt regressions."""
    harness = ConversationSinglePromptHarness()
    identifier = harness.make_issue_identifier(
        identification_guides=(ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE[IssueCode.MISLEADING_BEHAVIOR],)
    )

    mock_language_model = ConversationSinglePromptHarnessMock(response_text='{"issues": []}')
    with mock.patch(
        "vet.issue_identifiers.harnesses.conversation_single_prompt.build_language_model_from_config",
        return_value=mock_language_model,
    ):
        project_context = BaseProjectContext(
            file_contents_by_path=FrozenDict({"test.py": "print('hello')"}),
            cached_prompt_prefix="[ROLE=SYSTEM]\nSystem context here",
            instruction_context=SubrepoContextWithFormattedContext(
                repo_context_files=(),
                subrepo_context_strategy_label="docs",
                formatted_repo_context="Instruction context here",
            ),
        )
        conversation_inputs = ConversationInputs(
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
        config = VetConfig()

        generator = identifier.identify_issues(conversation_inputs, project_context, config)
        # Drain the generator to trigger the LLM call
        list(generator)

    assert len(mock_language_model.captured_prompts) == 1
    assert mock_language_model.captured_prompts[0] == snapshot


def _run_conversation_prompt_with_guides(
    guides: dict[IssueCode, object],
) -> str:
    """Helper: run identify_issues with given guides and return the captured prompt."""
    harness = ConversationSinglePromptHarness()
    identifier = harness.make_issue_identifier(
        identification_guides=tuple(guides[code] for code in ISSUE_CODES_FOR_CONVERSATION_HISTORY_CHECK)
    )

    mock_language_model = ConversationSinglePromptHarnessMock(response_text='{"issues": []}')
    with mock.patch(
        "vet.issue_identifiers.harnesses.conversation_single_prompt.build_language_model_from_config",
        return_value=mock_language_model,
    ):
        project_context = BaseProjectContext(
            file_contents_by_path=FrozenDict({"test.py": "print('hello')"}),
            cached_prompt_prefix="[ROLE=SYSTEM]\nSystem context here",
            instruction_context=SubrepoContextWithFormattedContext(
                repo_context_files=(),
                subrepo_context_strategy_label="docs",
                formatted_repo_context="Instruction context here",
            ),
        )
        conversation_inputs = ConversationInputs(
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
        config = VetConfig()

        generator = identifier.identify_issues(conversation_inputs, project_context, config)
        list(generator)

    assert len(mock_language_model.captured_prompts) == 1
    return mock_language_model.captured_prompts[0]


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
    prompt = _run_conversation_prompt_with_guides(merged_guides)
    assert prompt == snapshot
