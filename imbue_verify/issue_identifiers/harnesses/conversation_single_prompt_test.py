import pytest

from imbue_core.data_types import IssueCode
from imbue_core.ids import AssistantMessageID
from imbue_core.sculptor.state.chat_state import TextBlock
from imbue_core.sculptor.state.messages import AgentMessageSource
from imbue_core.sculptor.state.messages import ChatInputUserMessage
from imbue_core.sculptor.state.messages import LLMModel
from imbue_core.sculptor.state.messages import ResponseBlockAgentMessage
from imbue_tools.get_conversation_history.input_data_types import ConversationInputs
from imbue_tools.get_conversation_history.input_data_types import IdentifierInputs
from imbue_tools.get_conversation_history.input_data_types import (
    IdentifierInputsMissingError,
)
from imbue_verify.issue_identifiers.harnesses.conversation_single_prompt import (
    ConversationSinglePromptHarness,
)
from imbue_verify.issue_identifiers.identification_guides import (
    ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE,
)


def test_to_required_inputs() -> None:
    harness = ConversationSinglePromptHarness()
    classifier = harness.make_issue_identifier(
        identification_guides=(
            ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE[IssueCode.MISLEADING_BEHAVIOR],
        )
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
