HUMAN_ROLE = "HUMAN"
ASSISTANT_ROLE = "ASSISTANT"
USER_ROLE = "USER"
SYSTEM_ROLE = "SYSTEM"


def approximate_token_count(text: str) -> int:
    """Approximate token count using a fixed characters-per-token ratio.

    This is used for custom/user-defined models where we don't have access to the actual tokenizer.
    The ratio of 4.5 characters per token is a reasonable empirical estimate for most LLMs.

    In the future, it might be useful to allow users to configure this ratio per-model in models.json,
    but for now we use a single hardcoded value for simplicity.
    """
    return round(len(text) / 4.5)
