from functools import cached_property
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from typing import Self

import jinja2
from pydantic import Tag
from pydantic import computed_field

from vet.imbue_core.agents.configs import LanguageModelGenerationConfig
from vet.imbue_core.agents.configs import OpenAICompatibleModelConfig
from vet.imbue_core.async_utils import sync
from vet.imbue_core.frozen_utils import FrozenDict
from vet.imbue_core.pydantic_serialization import SerializableModel
from vet.imbue_core.pydantic_serialization import build_discriminator
from vet.imbue_tools.repo_utils.context_prefix import StrategyMode
from vet.imbue_tools.repo_utils.context_prefix import SubrepoContext
from vet.imbue_tools.repo_utils.context_prefix import SubrepoContextWithFormattedContext
from vet.imbue_tools.repo_utils.context_prefix import create_context_prompt_prefix
from vet.imbue_tools.repo_utils.context_prefix import get_repo_context
from vet.imbue_tools.repo_utils.context_retrieval import RepoContextManager
from vet.imbue_tools.repo_utils.file_system import InMemoryFileSystem
from vet.imbue_tools.repo_utils.subrepo_formatting import (
    REPO_CONTEXT_TEMPLATE_WITH_NO_MENTION_OF_DIFF,
)


@lru_cache
def _get_repo_context_manager_for_repo_path(repo_path: Path) -> RepoContextManager:
    """
    Wrapper around RepoContextManager.build() to cache the resulting repo context manager.

    Internally, the RepoContextManager object will itself cache the repo contents.
    """
    return RepoContextManager.build(repo_path)


class BaseProjectContext(SerializableModel):
    """
    Holds the context of the checked project including all its files.

    For LLM-based issue identifiers, no matter the scope, we want to use a fixed prompt prefix to leverage caching.
    We use the stable cached_prompt_prefix for that purpose.

    """

    object_type: str = "BaseProjectContext"

    file_contents_by_path: FrozenDict[str, str]
    cached_prompt_prefix: str
    # 0 - n most recent commits, with the most recent one being the first.
    # The state of the project (file_contents_by_path) is the state after the most recent commit.

    subrepo_context: SubrepoContext | None = None
    instruction_context: SubrepoContext | None = None
    repo_path: Path | None = None

    def get_file_contents(self, file_path: str) -> str | None:
        return self.file_contents_by_path.get(file_path)

    def get_computed_contexts(
        self,
    ) -> tuple[SubrepoContext | None, SubrepoContext | None]:
        """To match usage for LazyProjectContext; all fields are always computed because this isn't lazy"""
        return self.subrepo_context, self.instruction_context


class LazyProjectContext(SerializableModel):
    object_type: str = "LazyProjectContext"

    base_commit: str
    diff: str
    language_model_name: str
    repo_path: Path
    tokens_to_reserve: int

    # Optional context window override. If not provided, the model's default context window
    # will be looked up from the model registry (which fails for unknown models).
    context_window: int | None = None

    # If True, this is a custom/user-defined model (uses approximate token counting).
    is_custom_model: bool = False

    def get_file_contents(self, file_path: str) -> str | None:
        return self.file_contents_by_path.get(file_path)

    @classmethod
    def build(
        cls,
        base_commit: str,
        diff: str,
        language_model_name: str,
        repo_path: Path,
        # How many tokens to keep for the vet specific prompt and any output tokens.
        tokens_to_reserve: int,
        context_window: int | None = None,
        is_custom_model: bool = False,
    ) -> Self:
        return cls(
            base_commit=base_commit,
            diff=diff,
            language_model_name=language_model_name,
            repo_path=repo_path,
            tokens_to_reserve=tokens_to_reserve,
            context_window=context_window,
            is_custom_model=is_custom_model,
        )

    # The fields are computed and cached because they are quite expensive to compute.
    # We compose multiple repo_context prefixes, and also have to tokenize them to check their respective lengths.
    # Both of these operations are expensive

    @computed_field
    @cached_property
    def repo_context_manager(self) -> RepoContextManager:
        return _get_repo_context_manager_for_repo_path(self.repo_path)

    @computed_field
    @cached_property
    def original_content_by_path(self) -> InMemoryFileSystem:
        original_content_by_path = sync(self.repo_context_manager.get_full_repo_contents_at_commit)(self.base_commit)
        return original_content_by_path

    @computed_field
    @cached_property
    def content_by_path(self) -> InMemoryFileSystem:
        if self.diff:
            return sync(self.repo_context_manager.get_full_repo_contents_at_repo_state)(self.base_commit, self.diff)
        else:
            return self.original_content_by_path

    @computed_field
    @property
    def file_contents_by_path(self) -> FrozenDict[str, str]:
        return self.content_by_path.text_files

    @computed_field
    @cached_property
    def cached_prompt_prefix(self) -> str:
        prompt_prefix_template, prompt_prefix_params = create_context_prompt_prefix(
            repo_context=self.subrepo_context.formatted_repo_context,
        )
        env = jinja2.Environment(undefined=jinja2.StrictUndefined)
        jinja_template = env.from_string(prompt_prefix_template)
        cached_prompt_prefix = jinja_template.render(**prompt_prefix_params)
        return cached_prompt_prefix

    @computed_field
    @cached_property
    def modified_file_paths(self) -> frozenset[str]:
        modified_file_paths = []
        for file_path in self.content_by_path.files.keys():
            if self.content_by_path.get(file_path) != self.original_content_by_path.get(file_path):
                modified_file_paths.append(file_path)
        return frozenset(modified_file_paths)

    def _create_model_config(self) -> LanguageModelGenerationConfig:
        """Create the appropriate model config for context building.

        For custom models (is_custom_model=True), creates an OpenAICompatibleModelConfig
        that uses approximate token counting and the specified context window.

        For known models, creates a standard LanguageModelGenerationConfig that uses
        the model registry for token counting and context window lookup.
        """
        if self.is_custom_model:
            if self.context_window is None:
                raise ValueError(
                    "context_window must be provided when is_custom_model=True "
                    + "(custom models don't have a known context window)"
                )
            return OpenAICompatibleModelConfig(
                model_name=self.language_model_name,
                custom_base_url="",  # Not used for context building
                custom_api_key_env="",  # Not used for context building
                custom_context_window=self.context_window,
                custom_max_output_tokens=0,  # Not used for context building
            )
        else:
            return LanguageModelGenerationConfig(model_name=self.language_model_name)

    @computed_field
    @cached_property
    def subrepo_context(self) -> SubrepoContextWithFormattedContext:
        model_config = self._create_model_config()

        subrepo_context = get_repo_context(
            full_repo_contents=self.content_by_path,
            model_config=model_config,
            relevant_file_paths=self.modified_file_paths,
            tokens_to_reserve=self.tokens_to_reserve,
        )
        return subrepo_context

    def to_base_project_context(self) -> BaseProjectContext:
        return BaseProjectContext(
            file_contents_by_path=self.file_contents_by_path,
            cached_prompt_prefix=self.cached_prompt_prefix,
            subrepo_context=self.subrepo_context,
            instruction_context=self.instruction_context,
            repo_path=self.repo_path,
        )

    @computed_field
    @cached_property
    def instruction_context(self) -> SubrepoContextWithFormattedContext:
        model_config = self._create_model_config()
        return get_repo_context(
            model_config=model_config,
            full_repo_contents=self.content_by_path,
            relevant_file_paths=None,
            tokens_to_reserve=self.tokens_to_reserve,
            strategy_mode=StrategyMode.DOCS,
            template=REPO_CONTEXT_TEMPLATE_WITH_NO_MENTION_OF_DIFF,
        )

    def get_computed_contexts(
        self,
    ) -> tuple[
        SubrepoContextWithFormattedContext | None,
        SubrepoContextWithFormattedContext | None,
    ]:
        """Returns subrepo context and instruction context, but only if they have already been computed; those that haven't been computed are None"""
        # checking for presence in __dict__ does not trigger computation
        subrepo_context = self.subrepo_context if "subrepo_context" in self.__dict__ else None
        instruction_context = self.instruction_context if "instruction_context" in self.__dict__ else None
        return subrepo_context, instruction_context


ProjectContext = Annotated[
    Annotated[BaseProjectContext, Tag("BaseProjectContext")] | LazyProjectContext,
    build_discriminator(),
]
