import functools
from enum import StrEnum
from pathlib import Path
from typing import Any
from typing import Iterable
from typing import Mapping
from typing import assert_never

from loguru import logger
from pydantic import BaseModel
from pydantic import ConfigDict

from imbue_core.agents.configs import LanguageModelGenerationConfig
from imbue_core.async_monkey_patches import log_exception
from imbue_core.pydantic_serialization import SerializableModel
from imbue_tools.repo_utils.context_utils import escape_prompt_markers
from imbue_tools.repo_utils.context_utils import maybe_get_file_path_from_qualified_name
from imbue_tools.repo_utils.data_types import FileContextUnion
from imbue_tools.repo_utils.errors import ContextLengthExceededError
from imbue_tools.repo_utils.file_system import InMemoryFileSystem
from imbue_tools.repo_utils.python_imports import QualifiedName
from imbue_tools.repo_utils.python_imports import STANDARD_LIBRARIES
from imbue_tools.repo_utils.python_imports import get_global_imports
from imbue_tools.repo_utils.subrepo_formatting import BaseFilenamePattern
from imbue_tools.repo_utils.subrepo_formatting import ContextFormatStyle
from imbue_tools.repo_utils.subrepo_formatting import ExactFilenamePattern
from imbue_tools.repo_utils.subrepo_formatting import FilenamePattern
from imbue_tools.repo_utils.subrepo_formatting import IntersectionFilenamePattern
from imbue_tools.repo_utils.subrepo_formatting import NegatedFilenamePattern
from imbue_tools.repo_utils.subrepo_formatting import REPO_CONTEXT_TEMPLATE
from imbue_tools.repo_utils.subrepo_formatting import SubrepoContextMatchers
from imbue_tools.repo_utils.subrepo_formatting import UnionFilenamePattern
from imbue_tools.repo_utils.subrepo_formatting import compute_file_context_format_styles
from imbue_tools.repo_utils.subrepo_formatting import format_subrepo_context
from imbue_tools.repo_utils.subrepo_formatting import (
    parse_subrepo_context_matchers_from_toml,
)


class SubrepoContext(SerializableModel):
    repo_context_files: tuple[FileContextUnion, ...]
    subrepo_context_strategy_label: str


class SubrepoContextWithFormattedContext(SubrepoContext):
    formatted_repo_context: str


def is_qualified_name_from_stdlib(qualified_name: QualifiedName) -> bool:
    return qualified_name.top_level_name.value in STANDARD_LIBRARIES


def get_immediate_first_party_import_paths_for_python_file(
    current_file_path: str, full_repo_contents_map: InMemoryFileSystem
) -> set[str] | None:
    file_contents = full_repo_contents_map.get_text(current_file_path)
    if not file_contents or not current_file_path.endswith(".py"):
        return None

    try:
        global_imports = get_global_imports(file_contents)
    except SyntaxError as e:
        log_exception(
            e,
            "Failed to parse imports for {current_file_path}",
            current_file_path=current_file_path,
        )
        return None

    parent_names: set[QualifiedName] = set()
    for import_ in global_imports:
        parent_name = import_.qualified_name.parent_name
        parent_names.add(parent_name)

    imported_file_paths = set()
    all_file_paths = [Path(x) for x in full_repo_contents_map.text_files.keys()]
    for parent_name in parent_names:
        other_file_path = maybe_get_file_path_from_qualified_name(
            parent_name, all_file_paths
        )
        # if this doesn't exist it's likely not a first party import so we can ignore it
        if not other_file_path or is_qualified_name_from_stdlib(parent_name):
            continue
        imported_file_paths.add(str(other_file_path))

    return imported_file_paths


FULL_REPO_PATHSPEC = BaseFilenamePattern.from_lines(["/**"])
DOC_FILE_EXTENSIONS = [".md", ".txt"]
DOC_PATHSPEC = BaseFilenamePattern.from_lines(
    [f"**/*{ext}" for ext in DOC_FILE_EXTENSIONS]
)

# Common files that we want to exclude since they can be large and are of low signal for issue identification.
EXCLUSIONS_PATHSPEC = BaseFilenamePattern.from_lines(["uv.lock", "**/__snapshots__/**"])


def escape_gitignore_pattern(path: str) -> str:
    """
    Escape a path into a GitIgnore pattern that matches exactly the path.

    GitWildMatchPattern assigns special meaning to the following characters, which need to be escaped:
    `*`, `?`, `[`, `]` and `\\`.
    At the beginning of a line, we additionally need to escape leading `#` and `!` characters,
    and at the end of a line we need to escape trailing ` ` (space) characters.
    For simplicity, we simply escape these characters everywhere, which should still work correctly.
    """
    return (
        path.replace("\\", "\\\\")
        .replace("*", "\\*")
        .replace("?", "\\?")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("#", "\\#")
        .replace("!", "\\!")
        .replace(" ", "\\ ")
    )


def first_level_files_along_paths(file_paths: Iterable[str]) -> FilenamePattern:
    """
    Create a pathspec that matches all files along the given paths, but doesn't match adjacent directories.
    """
    # for each level in the path, we create an IntersectionFilenamePattern
    # which has one branch that matches everything starting with that path,
    # and another branch which matches everything except subdirectories starting with that path
    # then we OR these all together as a UnionFilenamePattern
    sorted_file_paths = sorted(file_paths)
    file_patterns = []
    for file_path in sorted_file_paths:
        for parent in Path(file_path).parents:
            escaped_parent = Path(escape_gitignore_pattern(str(parent)))
            match_all = BaseFilenamePattern.from_lines(
                [str("/" / escaped_parent / "*")]
            )
            match_except_subdirectories = (
                NegatedFilenamePattern.build_from_positive_pattern(
                    BaseFilenamePattern.from_lines([str("/" / escaped_parent / "*/*")])
                )
            )
            file_patterns.append(
                IntersectionFilenamePattern(
                    specs=(match_all, match_except_subdirectories)
                )
            )
    return UnionFilenamePattern(specs=tuple(file_patterns))


# cache this since it's reused across strategies
@functools.lru_cache(maxsize=5)
def make_docs_pathspec_along_paths(file_paths: frozenset[str]) -> FilenamePattern:
    """
    Create a pathspec that matches documentation files (.md, .txt) along each parent folder of the given file paths.
    """
    return IntersectionFilenamePattern(
        specs=(DOC_PATHSPEC, first_level_files_along_paths(file_paths=file_paths))
    )


INSTRUCTIONS_PATHSPEC = BaseFilenamePattern.from_lines(
    ["**/.claude.md", "**/CLAUDE.md", "**/AGENTS.md"]
)


@functools.lru_cache(maxsize=5)
def make_relevant_files_pathspec(file_paths: frozenset[str]) -> FilenamePattern:
    """
    Create a pathspec that matches the given file paths.
    """
    return ExactFilenamePattern(filenames=tuple(sorted(file_paths)))


# cache this since it's reused across strategies
@functools.lru_cache(maxsize=5)
def make_instructions_pathspec_along_paths(
    file_paths: frozenset[str],
) -> FilenamePattern:
    """
    Create a pathspec that matches instruction files (e.g. .claude.md, CLAUDE.md, AGENTS.md) along each parent folder of the given file paths.

    Should match a strict subset of make_docs_pathspec_along_paths.
    """
    return IntersectionFilenamePattern(
        specs=(
            INSTRUCTIONS_PATHSPEC,
            first_level_files_along_paths(file_paths=file_paths),
        )
    )


# cache this since it's reused across strategies
@functools.lru_cache(maxsize=5)
def make_imports_pathspec_for_paths(
    file_paths: frozenset[str], full_repo_contents: InMemoryFileSystem
) -> FilenamePattern:
    """
    Create a pathspec that matches Python files that are imported by the given file paths.
    """
    full_repo_python_file_contents_map = InMemoryFileSystem.build(
        {k: v for k, v in full_repo_contents.files.items() if k.endswith(".py")}
    )

    imported_file_paths = set()
    for file_path in file_paths:
        if file_path.endswith(".py"):
            # Include first party imports
            imported_paths = get_immediate_first_party_import_paths_for_python_file(
                file_path, full_repo_python_file_contents_map
            )
            if imported_paths:
                imported_file_paths.update(imported_paths)

    return ExactFilenamePattern(filenames=tuple(sorted(imported_file_paths)))


class SubrepoContextStrategy(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)
    label: str
    matchers: SubrepoContextMatchers


class SubrepoContextStrategyType(StrEnum):
    # defaults if we have relevant files
    FULL_REPO_CONTENTS = "full repo contents"
    RELEVANT_WHOLE_FILES_IMPORTS_DOCS_AND_ELSEWHERE_FILENAME = "relevant files + immediate imports + docs along relevant paths + filenames elsewhere"
    RELEVANT_WHOLE_FILES_IMPORTS_DOCS = (
        "relevant files + immediate imports + docs along relevant paths"
    )
    RELEVANT_WHOLE_FILES_AND_RELEVANT_STUBBIFIED_IMPORTS_DOCS = (
        "relevant files + stubbified imports + docs along relevant paths"
    )
    RELEVANT_WHOLE_FILES_DOCS = "relevant files + docs along relevant paths"
    RELEVANT_WHOLE_FILES_INSTRUCTIONS = (
        "relevant files + agent instructions along relevant paths"
    )
    RELEVANT_WHOLE_FILES = "relevant files"
    RELEVANT_STUBBIFIED_FILES = "relevant stubbified files"
    NOTHING = "nothing"

    # defaults if we don't have relevant files (missing FULL_REPO_CONTENTS and NOTHING because they're already listed for if we do have relevant files)
    WHOLE_DOCS_AND_OTHERWISE_FILENAMES = "docs + filenames elsewhere"
    WHOLE_INSTRUCTIONS_AND_OTHERWISE_FILENAMES = (
        "agent instructions + filenames elsewhere"
    )
    WHOLE_INSTRUCTIONS = "agent instructions"

    # defaults for providing instruction files if we have relevant files
    WHOLE_DOCS = "docs"
    WHOLE_INSTRUCTIONS_AND_RELEVANT_DOCS = "agent instructions + relevant docs"
    RELEVANT_DOCS = "relevant docs"
    RELEVANT_INSTRUCTIONS = "relevant agent instructions"

    # custom
    CUSTOM = "custom"


class StrategyMode(StrEnum):
    REGULAR = "regular"
    DOCS = "docs"


class AvailableInfoMode(StrEnum):
    YES_FILES = "yes_files"
    NO_FILES = "no_files"


DEFAULT_STRATEGY_TYPES: dict[
    tuple[StrategyMode, AvailableInfoMode], tuple[SubrepoContextStrategyType, ...]
] = {
    (StrategyMode.REGULAR, AvailableInfoMode.YES_FILES): (
        SubrepoContextStrategyType.FULL_REPO_CONTENTS,
        SubrepoContextStrategyType.RELEVANT_WHOLE_FILES_IMPORTS_DOCS_AND_ELSEWHERE_FILENAME,
        SubrepoContextStrategyType.RELEVANT_WHOLE_FILES_IMPORTS_DOCS,
        SubrepoContextStrategyType.RELEVANT_WHOLE_FILES_AND_RELEVANT_STUBBIFIED_IMPORTS_DOCS,
        SubrepoContextStrategyType.RELEVANT_WHOLE_FILES_DOCS,
        SubrepoContextStrategyType.RELEVANT_WHOLE_FILES_INSTRUCTIONS,
        SubrepoContextStrategyType.RELEVANT_WHOLE_FILES,
        SubrepoContextStrategyType.RELEVANT_STUBBIFIED_FILES,
        SubrepoContextStrategyType.NOTHING,
    ),
    (StrategyMode.REGULAR, AvailableInfoMode.NO_FILES): (
        SubrepoContextStrategyType.FULL_REPO_CONTENTS,
        SubrepoContextStrategyType.WHOLE_DOCS_AND_OTHERWISE_FILENAMES,
        SubrepoContextStrategyType.WHOLE_INSTRUCTIONS_AND_OTHERWISE_FILENAMES,
        SubrepoContextStrategyType.WHOLE_INSTRUCTIONS,
        SubrepoContextStrategyType.NOTHING,
    ),
    (StrategyMode.DOCS, AvailableInfoMode.YES_FILES): (
        SubrepoContextStrategyType.WHOLE_DOCS,
        SubrepoContextStrategyType.WHOLE_INSTRUCTIONS_AND_RELEVANT_DOCS,
        SubrepoContextStrategyType.RELEVANT_DOCS,
        SubrepoContextStrategyType.RELEVANT_INSTRUCTIONS,
        # these don't have `nothing` strategies because having some user instructions is crucial for
        # the issue identifier which uses this, whereas the others can do ok with just a diff
    ),
    (StrategyMode.DOCS, AvailableInfoMode.NO_FILES): (
        SubrepoContextStrategyType.WHOLE_DOCS,
        SubrepoContextStrategyType.WHOLE_INSTRUCTIONS,
    ),
}


def build_strategy(
    strategy_type: SubrepoContextStrategyType,
    full_repo_contents: InMemoryFileSystem,
    relevant_file_paths: frozenset[str] | None,
) -> SubrepoContextStrategy:
    match strategy_type:
        case SubrepoContextStrategyType.FULL_REPO_CONTENTS as s:
            return SubrepoContextStrategy(
                label=s,
                matchers=((ContextFormatStyle.FULL_FILE, FULL_REPO_PATHSPEC),),
            )
        case (
            SubrepoContextStrategyType.RELEVANT_WHOLE_FILES_IMPORTS_DOCS_AND_ELSEWHERE_FILENAME as s
        ):
            return SubrepoContextStrategy(
                label=s,
                matchers=(
                    (
                        ContextFormatStyle.FULL_FILE,
                        make_relevant_files_pathspec(relevant_file_paths),
                    ),
                    (
                        ContextFormatStyle.FULL_FILE,
                        make_imports_pathspec_for_paths(
                            relevant_file_paths, full_repo_contents
                        ),
                    ),
                    (
                        ContextFormatStyle.FULL_FILE,
                        make_docs_pathspec_along_paths(relevant_file_paths),
                    ),
                    (ContextFormatStyle.FILENAME_ONLY, FULL_REPO_PATHSPEC),
                ),
            )
        case SubrepoContextStrategyType.RELEVANT_WHOLE_FILES_IMPORTS_DOCS as s:
            return SubrepoContextStrategy(
                label=s,
                matchers=(
                    (
                        ContextFormatStyle.FULL_FILE,
                        make_relevant_files_pathspec(relevant_file_paths),
                    ),
                    (
                        ContextFormatStyle.FULL_FILE,
                        make_imports_pathspec_for_paths(
                            relevant_file_paths, full_repo_contents
                        ),
                    ),
                    (
                        ContextFormatStyle.FULL_FILE,
                        make_docs_pathspec_along_paths(relevant_file_paths),
                    ),
                    (ContextFormatStyle.HIDDEN, FULL_REPO_PATHSPEC),
                ),
            )
        case (
            SubrepoContextStrategyType.RELEVANT_WHOLE_FILES_AND_RELEVANT_STUBBIFIED_IMPORTS_DOCS as s
        ):
            return SubrepoContextStrategy(
                label=s,
                matchers=(
                    (
                        ContextFormatStyle.FULL_FILE,
                        make_relevant_files_pathspec(relevant_file_paths),
                    ),
                    (
                        ContextFormatStyle.STUB,
                        make_imports_pathspec_for_paths(
                            relevant_file_paths, full_repo_contents
                        ),
                    ),
                    (
                        ContextFormatStyle.FULL_FILE,
                        make_docs_pathspec_along_paths(relevant_file_paths),
                    ),
                    (ContextFormatStyle.HIDDEN, FULL_REPO_PATHSPEC),
                ),
            )
        case SubrepoContextStrategyType.RELEVANT_WHOLE_FILES_DOCS as s:
            return SubrepoContextStrategy(
                label=s,
                matchers=(
                    (
                        ContextFormatStyle.FULL_FILE,
                        make_relevant_files_pathspec(relevant_file_paths),
                    ),
                    (
                        ContextFormatStyle.FULL_FILE,
                        make_docs_pathspec_along_paths(relevant_file_paths),
                    ),
                    (ContextFormatStyle.HIDDEN, FULL_REPO_PATHSPEC),
                ),
            )
        case SubrepoContextStrategyType.RELEVANT_WHOLE_FILES_INSTRUCTIONS as s:
            return SubrepoContextStrategy(
                label=s,
                matchers=(
                    (
                        ContextFormatStyle.FULL_FILE,
                        make_relevant_files_pathspec(relevant_file_paths),
                    ),
                    (
                        ContextFormatStyle.FULL_FILE,
                        make_instructions_pathspec_along_paths(relevant_file_paths),
                    ),
                    (ContextFormatStyle.HIDDEN, FULL_REPO_PATHSPEC),
                ),
            )
        case SubrepoContextStrategyType.RELEVANT_WHOLE_FILES as s:
            return SubrepoContextStrategy(
                label=s,
                matchers=(
                    (
                        ContextFormatStyle.FULL_FILE,
                        make_relevant_files_pathspec(relevant_file_paths),
                    ),
                    (ContextFormatStyle.HIDDEN, FULL_REPO_PATHSPEC),
                ),
            )
        case SubrepoContextStrategyType.RELEVANT_STUBBIFIED_FILES as s:
            return SubrepoContextStrategy(
                label=s,
                matchers=(
                    (
                        ContextFormatStyle.STUB,
                        make_relevant_files_pathspec(relevant_file_paths),
                    ),
                    (ContextFormatStyle.HIDDEN, FULL_REPO_PATHSPEC),
                ),
            )
        case SubrepoContextStrategyType.NOTHING as s:
            return SubrepoContextStrategy(
                label=s,
                matchers=((ContextFormatStyle.HIDDEN, FULL_REPO_PATHSPEC),),
            )

        case SubrepoContextStrategyType.WHOLE_DOCS_AND_OTHERWISE_FILENAMES as s:
            return SubrepoContextStrategy(
                label=s,
                matchers=(
                    (ContextFormatStyle.FULL_FILE, DOC_PATHSPEC),
                    (ContextFormatStyle.FILENAME_ONLY, FULL_REPO_PATHSPEC),
                ),
            )
        case SubrepoContextStrategyType.WHOLE_INSTRUCTIONS_AND_OTHERWISE_FILENAMES as s:
            return SubrepoContextStrategy(
                label=s,
                matchers=(
                    (ContextFormatStyle.FULL_FILE, INSTRUCTIONS_PATHSPEC),
                    (ContextFormatStyle.FILENAME_ONLY, FULL_REPO_PATHSPEC),
                ),
            )
        case SubrepoContextStrategyType.WHOLE_INSTRUCTIONS as s:
            return SubrepoContextStrategy(
                label=s,
                matchers=(
                    (ContextFormatStyle.FULL_FILE, INSTRUCTIONS_PATHSPEC),
                    (ContextFormatStyle.HIDDEN, FULL_REPO_PATHSPEC),
                ),
            )

        case SubrepoContextStrategyType.WHOLE_DOCS as s:
            return SubrepoContextStrategy(
                label=s,
                matchers=(
                    (ContextFormatStyle.FULL_FILE, DOC_PATHSPEC),
                    (ContextFormatStyle.HIDDEN, FULL_REPO_PATHSPEC),
                ),
            )
        case SubrepoContextStrategyType.WHOLE_INSTRUCTIONS_AND_RELEVANT_DOCS as s:
            return SubrepoContextStrategy(
                label=s,
                matchers=(
                    (ContextFormatStyle.FULL_FILE, INSTRUCTIONS_PATHSPEC),
                    (
                        ContextFormatStyle.FULL_FILE,
                        make_docs_pathspec_along_paths(relevant_file_paths),
                    ),
                    (ContextFormatStyle.HIDDEN, FULL_REPO_PATHSPEC),
                ),
            )
        case SubrepoContextStrategyType.RELEVANT_DOCS as s:
            return SubrepoContextStrategy(
                label=s,
                matchers=(
                    (
                        ContextFormatStyle.FULL_FILE,
                        make_docs_pathspec_along_paths(relevant_file_paths),
                    ),
                    (ContextFormatStyle.HIDDEN, FULL_REPO_PATHSPEC),
                ),
            )
        case SubrepoContextStrategyType.RELEVANT_INSTRUCTIONS as s:
            return SubrepoContextStrategy(
                label=s,
                matchers=(
                    (
                        ContextFormatStyle.FULL_FILE,
                        make_instructions_pathspec_along_paths(relevant_file_paths),
                    ),
                    (ContextFormatStyle.HIDDEN, FULL_REPO_PATHSPEC),
                ),
            )
        case _ as unreachable:
            assert_never(unreachable)  # pyre-ignore[6]: pyre doesn't understand enums


def generate_subrepo_strategies(
    mode: StrategyMode,
    full_repo_contents: InMemoryFileSystem,
    relevant_file_paths: frozenset[str] | None = None,
) -> list[SubrepoContextStrategy]:
    available_info = (
        AvailableInfoMode.YES_FILES
        if relevant_file_paths
        else AvailableInfoMode.NO_FILES
    )
    return [
        build_strategy(strategy_type, full_repo_contents, relevant_file_paths)
        for strategy_type in DEFAULT_STRATEGY_TYPES[(mode, available_info)]
    ]


def select_desired_subrepo_strategies(
    full_repo_contents: InMemoryFileSystem,
    relevant_file_paths: frozenset[str] | None = None,
    subrepo_context_config: str | None = None,
    strategy_types_to_try: tuple[SubrepoContextStrategyType] | None = None,
    strategy_mode: (
        StrategyMode | None
    ) = None,  # if no config option is set, defaults to StrategyMode.REGULAR
) -> list[SubrepoContextStrategy]:
    num_ways_config_was_set = sum(
        1
        for v in [subrepo_context_config, strategy_types_to_try, strategy_mode]
        if v is not None
    )
    if num_ways_config_was_set > 1:
        assert (
            False
        ), "Can only specify one of subrepo_context_config, strategy_types_to_try, and strategy_mode"

    if subrepo_context_config is not None:
        # An explicit subrepo context config was provided. Use it exclusively.
        subrepo_context_matchers = parse_subrepo_context_matchers_from_toml(
            subrepo_context_config
        )
        return [
            SubrepoContextStrategy(
                label=SubrepoContextStrategyType.CUSTOM,
                matchers=subrepo_context_matchers,
            )
        ]
    elif strategy_types_to_try is not None:
        return [
            build_strategy(strategy_type, full_repo_contents, relevant_file_paths)
            for strategy_type in strategy_types_to_try
        ]
    else:
        strategy_mode_to_use = (
            strategy_mode if strategy_mode is not None else StrategyMode.REGULAR
        )
        return generate_subrepo_strategies(
            strategy_mode_to_use,
            full_repo_contents=full_repo_contents,
            relevant_file_paths=relevant_file_paths,
        )


# Caching results because this function is quite expensive. We compose multiple repo_context prefixes, and
# also have to tokenize them to check their respective lengths. Both of these operations are expensive,
@functools.lru_cache(maxsize=10)
def get_repo_context(
    model_config: LanguageModelGenerationConfig,
    full_repo_contents: InMemoryFileSystem,
    # how many tokens to reserve for additional prompt messages and output
    tokens_to_reserve: int,
    relevant_file_paths: frozenset[str] | None = None,
    subrepo_context_config: str | None = None,
    strategy_types_to_try: tuple[SubrepoContextStrategyType] | None = None,
    strategy_mode: (
        StrategyMode | None
    ) = None,  # if no config option is set, defaults to StrategyMode.REGULAR
    template: str = REPO_CONTEXT_TEMPLATE,
) -> SubrepoContextWithFormattedContext:
    """
    Make sure to try pass the same `full_repo_contents` when making multiple similar calls.
    Ordering of the dict is relevant for caching.
    """
    subrepo_context_strategies_to_try = select_desired_subrepo_strategies(
        full_repo_contents,
        relevant_file_paths,
        subrepo_context_config,
        strategy_types_to_try,
        strategy_mode,
    )

    last_context_length_exceeded_error: ContextLengthExceededError | None = None
    for subrepo_context_strategy in subrepo_context_strategies_to_try:
        try:
            path_to_format_style = compute_file_context_format_styles(
                file_paths=full_repo_contents.text_files.keys(),
                subrepo_context_matchers=subrepo_context_strategy.matchers,
                exclusions=EXCLUSIONS_PATHSPEC,
            )
            repo_context_str, repo_context_files = format_subrepo_context(
                full_repo_contents=full_repo_contents.text_files,
                model_config=model_config,
                path_to_format_style=path_to_format_style,
                tokens_to_reserve=tokens_to_reserve,
                template=template,
            )
            logger.info(
                "Selected subrepo context strategy: {}", subrepo_context_strategy.label
            )

            if subrepo_context_strategy.label == SubrepoContextStrategyType.NOTHING:
                # log an error if we have to use the NOTHING strategy, but still proceed with the call
                logger.error(
                    "Selected NOTHING subrepo context strategy; hopefully this doesn't happen too often!"
                )

            return SubrepoContextWithFormattedContext(
                formatted_repo_context=repo_context_str,
                repo_context_files=repo_context_files,
                subrepo_context_strategy_label=subrepo_context_strategy.label,
            )
        except ContextLengthExceededError as e:
            last_context_length_exceeded_error = e

    # We have exhausted all subrepo context strategies, and none of them worked.
    assert last_context_length_exceeded_error is not None
    raise last_context_length_exceeded_error from last_context_length_exceeded_error


# TODO: why not just render this here?
def create_context_prompt_prefix(repo_context: str) -> tuple[str, Mapping[str, Any]]:
    """Create a message that provides context about the repo contents."""
    cached_prefix_template = """[ROLE=SYSTEM_CACHED]
You are a detail-oriented, expert software developer.

Your goal is to help the user develop a particular commit to make a change to their program.

{{repo_context}}

{% if recent_git_history -%}

As additional context, here are some of the most recent changes made to the codebase (the output of `git log` and diffs for each of those commits):

```
{{recent_git_history}}
```
{% endif -%}
"""

    return (
        cached_prefix_template,
        dict(
            repo_context=escape_prompt_markers(repo_context),
            recent_git_history=None,
        ),
    )
