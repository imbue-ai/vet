from enum import Enum
from typing import Callable

from loguru import logger

from vet.repo_utils import VET_MAX_PROMPT_TOKENS

from vet.imbue_tools.types.vet_config import VetConfig


class ContentBudget(Enum):
    REPO_CONTEXT = 50
    DIFF = 30
    CONVERSATION = 10
    EXTRA_CONTEXT = 6
    GOAL = 4


def get_token_budget(total_available: int, budget: ContentBudget) -> int:
    return int(total_available * budget.value / 100)


def get_available_tokens(config: "VetConfig") -> int:
    lm_config = config.language_model_generation_config
    context_window = lm_config.get_max_context_length()
    return context_window - VET_MAX_PROMPT_TOKENS - config.max_output_tokens


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
