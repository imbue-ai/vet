import abc
from typing import Self


class CachedException(Exception, abc.ABC):
    """An exception that is stored in an LLM API cache.

    Provides convenience methods for storing and loading str representation for
    more efficient caching.
    """

    @classmethod
    @abc.abstractmethod
    def from_string(cls, data: str) -> Self: ...

    @abc.abstractmethod
    def to_string(self) -> str: ...


SPLIT_TOKEN: str = "|"


class PromptTooLongError(CachedException):
    """Exception raised when prompt too long for model context window size.

    We should cache these since no point trying same prompt again.
    """

    def __init__(self, prompt_len: int, max_prompt_len: int) -> None:
        self.prompt_len = prompt_len
        self.max_prompt_len = max_prompt_len

    @classmethod
    def from_string(cls, data: str) -> Self:
        prompt_len, max_prompt_len = data.split(SPLIT_TOKEN)[1:3]
        return cls(int(prompt_len), int(max_prompt_len))

    def to_string(self) -> str:
        string = SPLIT_TOKEN.join([self.__class__.__name__, str(self.prompt_len), str(self.max_prompt_len)])
        return string

    @property
    def required_reduction_fraction(self) -> float:
        return self.max_prompt_len / self.prompt_len


class BadAPIRequestError(CachedException):
    """Exception raised when request invalid (e.g. bad formatting, too long).

    Basically all miscellaneous errors due to input. We should cache these since no point trying same prompt again.
    """

    def __init__(self, error_message: str) -> None:
        self.error_message = error_message

    @classmethod
    def from_string(cls, data: str) -> Self:
        error_message = data.split(SPLIT_TOKEN)[1]
        return cls(error_message)

    def to_string(self) -> str:
        return SPLIT_TOKEN.join([self.__class__.__name__, self.error_message])


class UnsetCachePathError(Exception):
    def __init__(self) -> None:
        super().__init__(
            "Cache path must be specified in model config if you want to use model prompt-response caching. Caching can be disabled by setting `is_caching_enabled=False` when calling the LanguageModelAPI."
        )


class LanguageModelError(Exception):
    pass


class MissingAPIKeyError(LanguageModelError):
    pass


class RetriableLanguageModelError(LanguageModelError):
    pass


class TransientLanguageModelError(RetriableLanguageModelError):
    pass


class SafelyRetriableTransientLanguageModelError(TransientLanguageModelError):
    pass


class NewSeedRetriableLanguageModelError(RetriableLanguageModelError):
    pass


class LanguageModelRetryLimitError(Exception):
    pass


class LanguageModelInvalidModelNameError(ValueError):
    """Exception raised when an invalid model name is provided to a language model API."""

    def __init__(self, model_name: str, api_class_name: str, available_models: list[str]) -> None:
        self.model_name = model_name
        self.api_class_name = api_class_name
        self.available_models = available_models

        message = (
            f"Model with name={model_name} not available for {api_class_name}. Available models: {available_models}."
        )
        super().__init__(message)
