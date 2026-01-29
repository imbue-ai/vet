from imbue_core.errors import ExpectedError


class PromptAssemblyError(Exception):
    """Raised when there is an error assembling the prompt."""


class ContextLengthExceededError(PromptAssemblyError):
    """Raised when the context length exceeds the maximum allowed length."""


class InvalidVersionedConfigError(ExpectedError):
    pass


class MissingVersionedConfigError(ExpectedError):
    pass


class DiffApplicationError(Exception):
    pass


class DiffCalculationError(Exception):
    pass
