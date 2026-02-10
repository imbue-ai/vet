from enum import Enum
from typing import Callable

from loguru import logger

from vet.imbue_tools.types.vet_config import VetConfig


class ContextBudget(Enum):
    REPO_CONTEXT = 50
    DIFF = 30
    CONVERSATION = 10
    EXTRA_CONTEXT = 6
    GOAL = 4


def get_token_budget(total_available: int, budget: ContextBudget) -> int:
    return int(total_available * budget.value / 100)


def compute_tokens_remaining(config: VetConfig, prompt_overhead: int) -> int:
    """Compute available tokens for dynamic content given a specific prompt overhead.

    Available tokens = context_window - prompt_overhead - max_output_tokens.
    """
    lm_config = config.language_model_generation_config
    context_window = lm_config.get_max_context_length()
    return context_window - prompt_overhead - config.max_output_tokens


def get_available_tokens(config: VetConfig) -> int:
    """Compute available tokens using the max prompt overhead across all enabled harnesses.

    Use this for shared resources (e.g., diff, repo context) that are common across all
    identifiers and must fit within the budget of every harness.
    """
    return compute_tokens_remaining(config, config.max_prompt_overhead)


def truncate_to_token_limit(
    text: str,
    max_tokens: int,
    count_tokens: Callable[[str], int],
    label: str,
    truncate_end: bool = True,
) -> tuple[str, bool]:
    if not text:
        return text, False

    if max_tokens <= 0:
        logger.warning("{} budget is zero or negative, returning empty string", label.capitalize())
        return "", True

    token_count = count_tokens(text)
    if token_count <= max_tokens:
        return text, False

    logger.warning(
        "{} exceeds token limit ({} > {}), truncating",
        label.capitalize(),
        token_count,
        max_tokens,
    )

    if truncate_end:
        truncated = _find_truncation_point_from_end(text, max_tokens, count_tokens)
    else:
        truncated = _find_truncation_point_from_start(text, max_tokens, count_tokens)

    return truncated, True


def _find_truncation_point_from_end(
    text: str,
    max_tokens: int,
    count_tokens: Callable[[str], int],
) -> str:
    char_estimate = min(max_tokens * 4, len(text))

    low, high = 0, char_estimate
    result = ""

    if high < len(text) and count_tokens(text[:high]) <= max_tokens:
        low = high
        high = len(text)

    while low <= high:
        mid = (low + high) // 2
        candidate = text[:mid]
        if count_tokens(candidate) <= max_tokens:
            result = candidate
            low = mid + 1
        else:
            high = mid - 1

    return result


def _find_truncation_point_from_start(
    text: str,
    max_tokens: int,
    count_tokens: Callable[[str], int],
) -> str:
    char_estimate = min(max_tokens * 4, len(text))
    start_estimate = max(0, len(text) - char_estimate)

    low, high = 0, start_estimate
    result = text[start_estimate:]

    if count_tokens(result) > max_tokens:
        low = start_estimate
        high = len(text)

    while low <= high:
        mid = (low + high) // 2
        candidate = text[mid:]
        if count_tokens(candidate) <= max_tokens:
            result = candidate
            high = mid - 1
        else:
            low = mid + 1

    return result
