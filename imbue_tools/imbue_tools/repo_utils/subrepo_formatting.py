import functools
from collections import defaultdict
from enum import Enum
from typing import Annotated
from typing import Iterable
from typing import Mapping
from typing import Self
from typing import assert_never

import jinja2
from pathspec import GitIgnoreSpec
from pydantic import Tag

from imbue_core.agents.configs import LanguageModelGenerationConfig
from imbue_core.pydantic_serialization import SerializableModel
from imbue_core.pydantic_serialization import build_discriminator
from imbue_tools.repo_utils.context_utils import escape_all_jinja_variables
from imbue_tools.repo_utils.context_utils import escape_prompt_markers
from imbue_tools.repo_utils.data_types import FileContext
from imbue_tools.repo_utils.data_types import FileContextUnion
from imbue_tools.repo_utils.data_types import FilenameContext
from imbue_tools.repo_utils.data_types import FullFileContext
from imbue_tools.repo_utils.data_types import StubFileContext
from imbue_tools.repo_utils.errors import ContextLengthExceededError
from imbue_tools.repo_utils.stubify_file import stubify_code_file


class ContextFormatStyle(Enum):
    FULL_FILE = "FULL_FILE"
    STUB = "STUB"
    FILENAME_ONLY = "FILENAME_ONLY"
    HIDDEN = "HIDDEN"


class BaseFilenamePattern(SerializableModel):
    """
    Extends the functionality of `GitIgnoreSpec` to be serializable.
    """

    object_type: str = "BaseFilenamePattern"
    lines: tuple[str, ...]

    @functools.cached_property
    def git_ignore_spec(self) -> GitIgnoreSpec:
        return GitIgnoreSpec.from_lines(self.lines)

    @classmethod
    def from_lines(cls, lines: Iterable[str]) -> Self:
        return cls(lines=tuple(sorted(lines)))

    def match_file(self, file: str) -> bool:
        return self.git_ignore_spec.match_file(file)


class NegatedFilenamePattern(BaseFilenamePattern):
    """Matches everything except the files matched by the base pattern."""

    object_type: str = "NegatedFilenamePattern"

    def match_file(self, file: str) -> bool:
        return not self.git_ignore_spec.match_file(file)

    @classmethod
    def build_from_positive_pattern(cls, positive_pattern: BaseFilenamePattern) -> Self:
        return cls(lines=positive_pattern.lines)


class IntersectionFilenamePattern(SerializableModel):
    object_type: str = "IntersectionFilenamePattern"
    specs: tuple["FilenamePattern", ...]

    def match_file(self, file: str) -> bool:
        return all(spec.match_file(file) for spec in self.specs)


class UnionFilenamePattern(SerializableModel):
    object_type: str = "UnionFilenamePattern"
    specs: tuple["FilenamePattern", ...]

    def match_file(self, file: str) -> bool:
        return any(spec.match_file(file) for spec in self.specs)


class ExactFilenamePattern(SerializableModel):
    """
    Similar to a BaseFilenamePattern, but more efficient thanks to the use of a hash set.
    However, it only supports exact filename matches and no patterns.

    O(1) matching over n filenames, instead of O(n) with BaseFilenamePattern.
    """

    object_type: str = "ExactFilenamePattern"
    # Will match these exact filenames.
    # We store this as a tuple instead of frozenset to have deterministic ordering. Helps with snapshot tests.
    filenames: tuple[str, ...]

    def match_file(self, file: str) -> bool:
        return file in self.filenames_set

    @functools.cached_property
    def filenames_set(self) -> set[str]:
        return set(self.filenames)


FilenamePattern = Annotated[
    Annotated[BaseFilenamePattern, Tag("BaseFilenamePattern")]
    | Annotated[NegatedFilenamePattern, Tag("NegatedFilenamePattern")]
    | Annotated[IntersectionFilenamePattern, Tag("IntersectionFilenamePattern")]
    | Annotated[UnionFilenamePattern, Tag("UnionFilenamePattern")]
    | Annotated[ExactFilenamePattern, Tag("ExactFilenamePattern")],
    build_discriminator(),
]


SubrepoContextMatchers = tuple[tuple[ContextFormatStyle, FilenamePattern], ...]


@functools.lru_cache(maxsize=100)
def stubify_file_contents_cached(path: str, contents: str) -> str:
    # TODO: there's various flags here we could try
    # TODO: we may want an option to suppress comments, which end up being a large percent of the lines
    if path.endswith(".py"):
        return stubify_code_file(path, contents, keep_indent=True)
    else:
        # For non-Python files, maintain the full contents for now.
        return contents


def stubify_and_format_for_agent_context(
    path: str, contents: str | None
) -> StubFileContext:
    contents_to_use = contents if contents is not None else "RAW FILE CONTENTS"
    stub = stubify_file_contents_cached(path=path, contents=contents_to_use)
    return StubFileContext(path=path, stub=stub)


def format_filename_only_for_agent_context(path: str) -> FilenameContext:
    return FilenameContext(path=path)


def format_full_file_for_agent_context(path: str, contents: str) -> FullFileContext:
    return FullFileContext(path=path, contents=contents)


BASE_REPO_CONTEXT_TEMPLATE = """
<REPO_CONTEXT>
{{repo_context}}
</REPO_CONTEXT>
"""

REPO_CONTEXT_TEMPLATE_WITH_NO_MENTION_OF_DIFF = (
    """
{% if not is_shortened %}For context, here are the contents of all files currently in the project:
{% else %}The project's repository is too large to show in full, so we have chosen a useful subset for your context.
Files in the repository may be shown in either full, stubified, or filename-only form{% if has_hidden_files %}, or they may be hidden entirely{% endif %}. Here are the contents of some of the files in the repository:{% endif %}
"""
    + BASE_REPO_CONTEXT_TEMPLATE
)

REPO_CONTEXT_TEMPLATE = (
    REPO_CONTEXT_TEMPLATE_WITH_NO_MENTION_OF_DIFF
    + """

If any files have been changed, the changes will be described next. Otherwise, you can assume this is the current state of the project.
"""
)


def format_file_for_agent_context(
    path: str, contents: str, format_style: ContextFormatStyle
) -> FileContextUnion | None:
    if format_style == ContextFormatStyle.FULL_FILE:
        return format_full_file_for_agent_context(path, contents)
    elif format_style == ContextFormatStyle.STUB:
        return stubify_and_format_for_agent_context(path, contents)
    elif format_style == ContextFormatStyle.FILENAME_ONLY:
        return format_filename_only_for_agent_context(path)
    elif format_style == ContextFormatStyle.HIDDEN:
        return None
    else:
        assert_never(format_style)  # pyre-ignore[6]: pyre doesn't understand enums


@functools.lru_cache(maxsize=20)
def parse_subrepo_context_matchers_from_toml(
    subrepo_context_config_toml: str,
) -> SubrepoContextMatchers:
    current_mode: ContextFormatStyle
    matchers = []
    for line in subrepo_context_config_toml.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("["):
            current_mode = ContextFormatStyle[line.replace("[", "").replace("]", "").upper()]  # type: ignore
            continue

        exclude_spec = BaseFilenamePattern.from_lines([line])
        matchers.append((current_mode, exclude_spec))
    return tuple(matchers)


def compute_file_format_style(
    file_path: str,
    subrepo_context_matchers: SubrepoContextMatchers,
    exclusions: FilenamePattern | None = None,
) -> ContextFormatStyle:
    for matcher_format, matcher in subrepo_context_matchers:
        if matcher.match_file(file_path):
            if (
                exclusions
                and matcher_format != ContextFormatStyle.HIDDEN
                and exclusions.match_file(file_path)
            ):
                # Exclusions override any non-hidden format and downgrade it to FILENAME_ONLY.
                return ContextFormatStyle.FILENAME_ONLY
            # Return the first match
            return matcher_format
    return ContextFormatStyle.HIDDEN


def compute_file_context_format_styles(
    file_paths: Iterable[str],
    subrepo_context_matchers: SubrepoContextMatchers,
    exclusions: FilenamePattern | None = None,
) -> Mapping[str, ContextFormatStyle]:
    return {
        file_path: compute_file_format_style(
            file_path, subrepo_context_matchers, exclusions
        )
        for file_path in file_paths
    }


def get_estimated_lower_bound_token_count_for_text_and_model(
    text: str, model_name: str
) -> int:
    # A factor of 1/4.5 appears to be a reasonable empirical estimate for current models.
    # We use a slighly smaller factor (1/5) to give more of a lower bound estimate.
    return round(len(text) / 5)


def format_all_for_agent(repo_contents: tuple[FileContext, ...]) -> dict[str, str]:
    return {contents.path: contents.format_for_agent() for contents in repo_contents}


def format_subrepo(formatted_repo_contents: Mapping[str, str]) -> str:
    repo_context_str = "".join(
        [
            contents
            for contents in formatted_repo_contents.values()
            if contents is not None
        ]
    )
    return escape_all_jinja_variables(escape_prompt_markers(repo_context_str))


def format_subrepo_context_full(repo: Mapping[str, str]) -> str:
    """Like get_repo_context but there's no checking for context limits (so we can use the api checks instead)
    and the selected strategy is always the full repo contents."""
    formatted_repo_context = format_subrepo(
        format_all_for_agent(
            format_subrepo_context_into_filecontexts(
                full_repo_contents=repo,
                path_to_format_style=defaultdict(
                    lambda: ContextFormatStyle.FULL_FILE, {}
                ),
            )
        )
    )

    repo_context_core_prompt = formatted_subrepo_to_prompt(
        repo_context_str=formatted_repo_context,
        is_shortened=False,
        has_hidden_files=False,
        template=BASE_REPO_CONTEXT_TEMPLATE,
    )

    return repo_context_core_prompt


def formatted_subrepo_to_prompt(
    repo_context_str: str, is_shortened: bool, has_hidden_files: bool, template: str
) -> str:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    jinja_template = env.from_string(template)
    repo_context_prompt = jinja_template.render(
        repo_context=repo_context_str,
        is_shortened=is_shortened,
        has_hidden_files=has_hidden_files,
    )
    return repo_context_prompt


def format_subrepo_context_into_filecontexts(
    full_repo_contents: Mapping[str, str],
    path_to_format_style: Mapping[str, ContextFormatStyle],
) -> tuple[FileContextUnion, ...]:
    repo_contents = tuple(
        format_file_for_agent_context(path, contents, path_to_format_style[path])
        for path, contents in full_repo_contents.items()
    )
    repo_contents_with_hidden_removed = tuple(
        contents for contents in repo_contents if contents is not None
    )
    return repo_contents_with_hidden_removed


def build_context_from_filecontexts(
    repo_contents_with_hidden_removed: tuple[FileContextUnion, ...],
    model_config: LanguageModelGenerationConfig,
    # how many tokens to reserve for additional prompt messages and output
    tokens_to_reserve: int,
    template: str = REPO_CONTEXT_TEMPLATE,
    path_to_format_style: Mapping[str, ContextFormatStyle] | None = None,
) -> str:
    """
    Returns the repo contents formatted according to the format styles as a string.
    Includes (at least if the default template is used) an explanation at the beginning
    saying that these are the contents of the repo, potentially truncated or hidden.

    If there are no repo contents, returns an empty string.
    """

    if not repo_contents_with_hidden_removed:
        return ""

    max_context_length = model_config.get_max_context_length()
    available_tokens = max_context_length - tokens_to_reserve

    formatted_repo_contents_with_hidden_removed = format_all_for_agent(
        repo_contents_with_hidden_removed
    )

    repo_context_str = format_subrepo(formatted_repo_contents_with_hidden_removed)

    if model_config.is_custom_model():
        # For custom models, approximate_token_count is already fast, so skip the estimation step.
        full_repo_context_token_count = model_config.count_tokens(repo_context_str)
    else:
        # First use an estimation of the token count to see if we are likely below the maximum length. Then
        # double-check with the exact token count.
        # We do this because getting the exact token count is quite slow.
        estimated_full_repo_context_token_count = (
            get_estimated_lower_bound_token_count_for_text_and_model(
                repo_context_str, model_config.model_name
            )
        )
        if estimated_full_repo_context_token_count > available_tokens:
            raise ContextLengthExceededError(
                f"Estimated context has size {estimated_full_repo_context_token_count}; available tokens {available_tokens}"
            )
        full_repo_context_token_count = model_config.count_tokens(repo_context_str)
    if full_repo_context_token_count > available_tokens:
        raise ContextLengthExceededError(
            f"Context has size {full_repo_context_token_count}; available tokens {available_tokens}"
        )

    if path_to_format_style is None:
        path_to_format_style = {
            contents.path: ContextFormatStyle.FULL_FILE
            for contents in repo_contents_with_hidden_removed
        }

    is_shortened = any(
        [
            style != ContextFormatStyle.FULL_FILE
            for style in path_to_format_style.values()
        ]
    )
    has_hidden_files = any(
        [style == ContextFormatStyle.HIDDEN for style in path_to_format_style.values()]
    )

    repo_context_prompt = formatted_subrepo_to_prompt(
        repo_context_str=repo_context_str,
        is_shortened=is_shortened,
        has_hidden_files=has_hidden_files,
        template=template,
    )
    return repo_context_prompt


def format_subrepo_context(
    full_repo_contents: Mapping[str, str],
    path_to_format_style: Mapping[str, ContextFormatStyle],
    model_config: LanguageModelGenerationConfig,
    # how many tokens to reserve for additional prompt messages and output
    tokens_to_reserve: int,
    template: str = REPO_CONTEXT_TEMPLATE,
) -> tuple[str, tuple[FileContextUnion, ...]]:
    repo_contents_tuple = format_subrepo_context_into_filecontexts(
        full_repo_contents, path_to_format_style
    )
    repo_context_str = build_context_from_filecontexts(
        repo_contents_tuple,
        model_config,
        tokens_to_reserve,
        template,
        path_to_format_style,
    )
    return repo_context_str, repo_contents_tuple
