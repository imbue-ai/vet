from typing import Callable

import tiktoken
from hypothesis import given, settings, strategies as st, assume

from vet.truncation import ContextBudget, get_token_budget, truncate_to_token_limit


def word_count(text: str) -> int:
    return len(text.split())


def char_count(text: str) -> int:
    return len(text)


def char_div4_count(text: str) -> int:
    return len(text) // 4 + 1 if text else 0


_tiktoken_encoder = tiktoken.get_encoding("cl100k_base")


def tiktoken_count(text: str) -> int:
    return len(_tiktoken_encoder.encode(text))


SIMPLE_TOKEN_COUNTERS: list[Callable[[str], int]] = [
    word_count,
    char_count,
    char_div4_count,
]

ALL_TOKEN_COUNTERS: list[Callable[[str], int]] = SIMPLE_TOKEN_COUNTERS + [tiktoken_count]

ascii_text = st.text(
    alphabet=st.characters(min_codepoint=32, max_codepoint=126),
    min_size=0,
    max_size=1000,
)

unicode_text = st.text(
    alphabet=st.characters(
        min_codepoint=32,
        max_codepoint=0xFFFF,
        blacklist_categories=("Cs",),
    ),
    min_size=0,
    max_size=500,
)

code_text = st.from_regex(
    r"[a-zA-Z_][a-zA-Z0-9_]{0,20}(\s*[+\-*/=<>!&|]+\s*[a-zA-Z_][a-zA-Z0-9_]{0,20}){0,10}",
    fullmatch=True,
)

whitespace_text = st.text(alphabet=" \t\n\r", min_size=0, max_size=200)

repeated_char_text = st.builds(
    lambda char, count: char * count,
    char=st.characters(min_codepoint=32, max_codepoint=126),
    count=st.integers(min_value=0, max_value=500),
)

mixed_text = st.builds(
    lambda code, comment, uni: f"{code} // {comment}\n{uni}",
    code=st.from_regex(r"[a-z_][a-z0-9_]{0,10}", fullmatch=True),
    comment=ascii_text,
    uni=st.text(min_size=0, max_size=100),
)


def test_context_budgets_sum_to_100():
    total = sum(budget.value for budget in ContextBudget)
    assert total == 100, f"ContextBudget values must sum to 100, got {total}"


@given(
    total_tokens=st.integers(min_value=0, max_value=1_000_000),
    budget=st.sampled_from(list(ContextBudget)),
)
def test_get_token_budget_is_mathematically_correct(total_tokens: int, budget: ContextBudget):
    result = get_token_budget(total_tokens, budget)
    expected = total_tokens * budget.value // 100
    assert result == expected


@given(
    text=st.text(min_size=0, max_size=10_000),
    max_tokens=st.integers(min_value=0, max_value=10_000),
    truncate_end=st.booleans(),
    counter_idx=st.integers(min_value=0, max_value=len(SIMPLE_TOKEN_COUNTERS) - 1),
)
def test_truncate_always_respects_token_limit_simple(text: str, max_tokens: int, truncate_end: bool, counter_idx: int):
    count_tokens = SIMPLE_TOKEN_COUNTERS[counter_idx]

    result, _ = truncate_to_token_limit(
        text,
        max_tokens=max_tokens,
        count_tokens=count_tokens,
        label="test",
        truncate_end=truncate_end,
    )

    assert count_tokens(result) <= max_tokens, (
        f"Token limit violated: got {count_tokens(result)} > {max_tokens} "
        f"(counter={count_tokens.__name__}, truncate_end={truncate_end})"
    )


@given(
    text=st.text(min_size=1, max_size=1000),
    max_tokens=st.integers(min_value=1, max_value=100),
)
def test_truncate_end_produces_prefix(text: str, max_tokens: int):
    result, was_truncated = truncate_to_token_limit(
        text,
        max_tokens=max_tokens,
        count_tokens=char_count,
        label="test",
        truncate_end=True,
    )

    assert text.startswith(result), f"Result '{result[:50]}...' is not a prefix of original"

    if was_truncated:
        assert len(result) < len(text)


@given(
    text=st.text(min_size=1, max_size=1000),
    max_tokens=st.integers(min_value=1, max_value=100),
)
def test_truncate_start_produces_suffix(text: str, max_tokens: int):
    result, was_truncated = truncate_to_token_limit(
        text,
        max_tokens=max_tokens,
        count_tokens=char_count,
        label="test",
        truncate_end=False,
    )

    assert text.endswith(result), f"Result '...{result[-50:]}' is not a suffix of original"

    if was_truncated:
        assert len(result) < len(text)


@given(
    text=st.text(min_size=0, max_size=1000),
    budget_multiplier=st.integers(min_value=1, max_value=10),
    counter_idx=st.integers(min_value=0, max_value=len(SIMPLE_TOKEN_COUNTERS) - 1),
)
def test_text_within_budget_unchanged(text: str, budget_multiplier: int, counter_idx: int):
    count_tokens = SIMPLE_TOKEN_COUNTERS[counter_idx]
    token_count = count_tokens(text)

    max_tokens = token_count * budget_multiplier + 10

    result, was_truncated = truncate_to_token_limit(
        text,
        max_tokens=max_tokens,
        count_tokens=count_tokens,
        label="test",
    )

    assert result == text
    assert was_truncated is False


@given(counter_idx=st.integers(min_value=0, max_value=len(SIMPLE_TOKEN_COUNTERS) - 1))
def test_empty_text_always_returns_empty(counter_idx: int):
    count_tokens = SIMPLE_TOKEN_COUNTERS[counter_idx]

    result, was_truncated = truncate_to_token_limit(
        "",
        max_tokens=100,
        count_tokens=count_tokens,
        label="test",
    )

    assert result == ""
    assert was_truncated is False


@given(
    text=st.text(min_size=1, max_size=1000),
    counter_idx=st.integers(min_value=0, max_value=len(SIMPLE_TOKEN_COUNTERS) - 1),
)
def test_zero_budget_returns_empty_and_truncated(text: str, counter_idx: int):
    count_tokens = SIMPLE_TOKEN_COUNTERS[counter_idx]

    assume(count_tokens(text) > 0)

    result, was_truncated = truncate_to_token_limit(
        text,
        max_tokens=0,
        count_tokens=count_tokens,
        label="test",
    )

    assert result == ""
    assert was_truncated is True


@given(
    text=st.text(min_size=10, max_size=1000),
    max_tokens=st.integers(min_value=1, max_value=50),
)
def test_truncation_preserves_maximum_content(text: str, max_tokens: int):
    assume(char_count(text) > max_tokens)

    result, was_truncated = truncate_to_token_limit(
        text,
        max_tokens=max_tokens,
        count_tokens=char_count,
        label="test",
        truncate_end=True,
    )

    assert was_truncated is True
    assert char_count(result) <= max_tokens

    if max_tokens > 0:
        assert len(result) > 0 or max_tokens == 0


@settings(max_examples=20)
@given(
    text=ascii_text,
    max_tokens=st.integers(min_value=0, max_value=500),
    truncate_end=st.booleans(),
)
def test_truncate_respects_limit_tiktoken_ascii(text: str, max_tokens: int, truncate_end: bool):
    result, _ = truncate_to_token_limit(
        text,
        max_tokens=max_tokens,
        count_tokens=tiktoken_count,
        label="test",
        truncate_end=truncate_end,
    )

    assert tiktoken_count(result) <= max_tokens


@settings(max_examples=20)
@given(
    text=unicode_text,
    max_tokens=st.integers(min_value=0, max_value=200),
    truncate_end=st.booleans(),
)
def test_truncate_respects_limit_tiktoken_unicode(text: str, max_tokens: int, truncate_end: bool):
    result, _ = truncate_to_token_limit(
        text,
        max_tokens=max_tokens,
        count_tokens=tiktoken_count,
        label="test",
        truncate_end=truncate_end,
    )

    assert tiktoken_count(result) <= max_tokens


@settings(max_examples=20)
@given(
    text=code_text,
    max_tokens=st.integers(min_value=1, max_value=100),
    truncate_end=st.booleans(),
)
def test_truncate_respects_limit_tiktoken_code(text: str, max_tokens: int, truncate_end: bool):
    result, _ = truncate_to_token_limit(
        text,
        max_tokens=max_tokens,
        count_tokens=tiktoken_count,
        label="test",
        truncate_end=truncate_end,
    )

    assert tiktoken_count(result) <= max_tokens


@settings(max_examples=20)
@given(
    text=repeated_char_text,
    max_tokens=st.integers(min_value=0, max_value=100),
    truncate_end=st.booleans(),
)
def test_truncate_respects_limit_tiktoken_repeated(text: str, max_tokens: int, truncate_end: bool):
    result, _ = truncate_to_token_limit(
        text,
        max_tokens=max_tokens,
        count_tokens=tiktoken_count,
        label="test",
        truncate_end=truncate_end,
    )

    assert tiktoken_count(result) <= max_tokens


@settings(max_examples=20)
@given(
    text=mixed_text,
    max_tokens=st.integers(min_value=1, max_value=100),
    truncate_end=st.booleans(),
)
def test_truncate_respects_limit_tiktoken_mixed(text: str, max_tokens: int, truncate_end: bool):
    result, _ = truncate_to_token_limit(
        text,
        max_tokens=max_tokens,
        count_tokens=tiktoken_count,
        label="test",
        truncate_end=truncate_end,
    )

    assert tiktoken_count(result) <= max_tokens


@settings(max_examples=20)
@given(
    text=st.text(min_size=10, max_size=500),
    max_tokens=st.integers(min_value=1, max_value=50),
)
def test_truncation_is_maximally_efficient_tiktoken(text: str, max_tokens: int):
    assume(tiktoken_count(text) > max_tokens)

    result, was_truncated = truncate_to_token_limit(
        text,
        max_tokens=max_tokens,
        count_tokens=tiktoken_count,
        label="test",
        truncate_end=True,
    )

    assert was_truncated is True
    assert tiktoken_count(result) <= max_tokens


@settings(max_examples=20)
@given(
    text=st.text(min_size=10, max_size=500),
    max_tokens=st.integers(min_value=1, max_value=50),
)
def test_truncation_from_start_is_maximally_efficient_tiktoken(text: str, max_tokens: int):
    assume(tiktoken_count(text) > max_tokens)

    result, was_truncated = truncate_to_token_limit(
        text,
        max_tokens=max_tokens,
        count_tokens=tiktoken_count,
        label="test",
        truncate_end=False,
    )

    assert was_truncated is True
    assert tiktoken_count(result) <= max_tokens
    assert text.endswith(result)


@settings(max_examples=10)
@given(text=whitespace_text)
def test_truncate_whitespace_only_tiktoken(text: str):
    max_tokens = 5

    result, _ = truncate_to_token_limit(
        text,
        max_tokens=max_tokens,
        count_tokens=tiktoken_count,
        label="test",
        truncate_end=True,
    )

    assert tiktoken_count(result) <= max_tokens


def test_truncate_emoji_sequence():
    text = "Hello 👋🏽 World 🌍 Test 🎉🎊🎁"
    max_tokens = 5

    result, was_truncated = truncate_to_token_limit(
        text,
        max_tokens=max_tokens,
        count_tokens=tiktoken_count,
        label="test",
        truncate_end=True,
    )

    assert tiktoken_count(result) <= max_tokens
    assert text.startswith(result)


def test_truncate_cjk_characters():
    text = "这是一个测试文本，包含中文字符。Hello World! 日本語テスト。"
    max_tokens = 10

    result, was_truncated = truncate_to_token_limit(
        text,
        max_tokens=max_tokens,
        count_tokens=tiktoken_count,
        label="test",
        truncate_end=True,
    )

    assert tiktoken_count(result) <= max_tokens
    assert text.startswith(result)


def test_truncate_mixed_scripts():
    text = "Hello Привет مرحبا שלום 你好 こんにちは"
    max_tokens = 8

    result, was_truncated = truncate_to_token_limit(
        text,
        max_tokens=max_tokens,
        count_tokens=tiktoken_count,
        label="test",
        truncate_end=True,
    )

    assert tiktoken_count(result) <= max_tokens
    assert text.startswith(result)
