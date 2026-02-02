class PromptAssemblyError(Exception):
    """Raised when there is an error assembling the prompt."""


class ContextLengthExceededError(PromptAssemblyError):
    """Raised when the context length exceeds the maximum allowed length."""


class DiffApplicationError(Exception):
    pass
