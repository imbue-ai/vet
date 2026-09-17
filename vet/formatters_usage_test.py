from __future__ import annotations

from vet.formatters import format_run_usage
from vet.formatters import usage_to_dict
from vet.imbue_core.data_types import InvocationInfo
from vet.imbue_core.data_types import IssueIdentificationDebugInfo
from vet.imbue_core.data_types import IssueIdentificationLLMResponseMetadata
from vet.imbue_core.data_types import LLMResponse
from vet.imbue_core.data_types import RunUsage
from vet.imbue_core.data_types import aggregate_run_usage


def _llm_response(invocation_info: InvocationInfo | None) -> LLMResponse:
    return LLMResponse(
        metadata=IssueIdentificationLLMResponseMetadata(),
        raw_response=("ok",),
        invocation_info=invocation_info,
    )


def test_aggregate_run_usage_sums_tokens_and_cost() -> None:
    debug_info = IssueIdentificationDebugInfo(
        llm_responses=(
            _llm_response(
                InvocationInfo(
                    input_tokens=1000,
                    output_tokens=200,
                    cache_creation_input_tokens=50,
                    cache_read_input_tokens=100,
                    cost=0.01,
                    duration_ms=100.0,
                )
            ),
            _llm_response(
                InvocationInfo(
                    input_tokens=500,
                    output_tokens=50,
                    cost=0.032,
                    duration_ms=50.5,
                )
            ),
        )
    )

    usage = aggregate_run_usage(debug_info)

    assert usage == RunUsage(
        input_tokens=1500,
        output_tokens=250,
        cache_creation_input_tokens=50,
        cache_read_input_tokens=100,
        cost_usd=0.042,
        llm_calls=2,
        duration_ms=150.5,
    )


def test_aggregate_run_usage_prefers_total_input_tokens() -> None:
    debug_info = IssueIdentificationDebugInfo(
        llm_responses=(
            _llm_response(
                InvocationInfo(
                    input_tokens=100,
                    total_input_tokens=250,
                    output_tokens=10,
                    cost=0.0,
                )
            ),
        )
    )

    usage = aggregate_run_usage(debug_info)

    assert usage.input_tokens == 250
    assert usage.cost_usd == 0.0
    assert usage.llm_calls == 1


def test_aggregate_run_usage_unknown_cost_when_all_missing() -> None:
    debug_info = IssueIdentificationDebugInfo(
        llm_responses=(
            _llm_response(InvocationInfo(input_tokens=10, output_tokens=5)),
            _llm_response(InvocationInfo(input_tokens=20, output_tokens=8)),
        )
    )

    usage = aggregate_run_usage(debug_info)

    assert usage.input_tokens == 30
    assert usage.output_tokens == 13
    assert usage.cost_usd is None
    assert usage.llm_calls == 2


def test_aggregate_run_usage_counts_calls_without_invocation_info() -> None:
    debug_info = IssueIdentificationDebugInfo(llm_responses=(_llm_response(None),))

    usage = aggregate_run_usage(debug_info)

    assert usage.llm_calls == 1
    assert usage.input_tokens == 0
    assert usage.cost_usd is None


def test_format_run_usage_with_cost() -> None:
    summary = format_run_usage(RunUsage(input_tokens=12400, output_tokens=1820, cost_usd=0.042, llm_calls=2))
    assert summary == "Cost: $0.042 · 12,400 in / 1,820 out tokens · 2 LLM calls"


def test_format_run_usage_unknown_cost() -> None:
    summary = format_run_usage(RunUsage(input_tokens=100, output_tokens=20, llm_calls=1))
    assert summary == "Cost: unknown · 100 in / 20 out tokens · 1 LLM call"


def test_format_run_usage_omits_when_no_calls() -> None:
    assert format_run_usage(RunUsage()) is None


def test_usage_to_dict_includes_null_cost() -> None:
    payload = usage_to_dict(RunUsage(input_tokens=10, output_tokens=2, llm_calls=1))
    assert payload["cost_usd"] is None
    assert payload["input_tokens"] == 10
    assert payload["llm_calls"] == 1
