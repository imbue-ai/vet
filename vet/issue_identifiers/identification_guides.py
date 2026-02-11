from __future__ import annotations

from vet.imbue_core.data_types import CustomGuidesConfig
from vet.imbue_core.data_types import GuideMode
from vet.imbue_core.data_types import IssueCode
from vet.imbue_core.pydantic_serialization import SerializableModel


class IssueIdentificationGuide(SerializableModel):
    """
    An LLM-readable guide for identifying issues of a given type from a provided context.
    """

    issue_code: IssueCode
    guide: str
    additional_guide_for_agent: str | None = None
    examples: tuple[str, ...] = ()
    exceptions: tuple[str, ...] = ()


# Define your issue identification guides here.
ISSUE_IDENTIFICATION_GUIDES: tuple[IssueIdentificationGuide, ...] = (
    IssueIdentificationGuide(
        issue_code=IssueCode.COMMIT_MESSAGE_MISMATCH,
        guide="\n".join(
            [
                "- The diff must completely fulfill the user's request.",
                "- Look for incomplete implementations:",
                "   - When the user asks for changes 'throughout', 'everywhere', or 'all', verify ALL instances are modified",
                "   - If multiple changes are requested, ensure each one is fully implemented",
                "   - Check that fixes are applied to all occurrences of a pattern, not just some",
                "- Look for scope mismatches:",
                "   - Changes only in initialization when they should apply during execution",
                "   - Modifications to only one file when multiple files need updates",
                "   - Partial refactoring that leaves related code unchanged",
                "- Look for unauthorized changes:",
                "   - Configuration changes (linting, build, test settings) not requested",
                "   - New features or options beyond the request",
                "   - Changes to unrelated code",
                "- Look for unintended removals:",
                "   - Removal of project-specific configuration or settings that should be preserved",
                "   - Deletion of functionality that is still needed",
                "   - Loss of necessary entries when replacing configuration files",
                "- Look for unintended side effects:",
                "   - Changes that affect code paths or functionality beyond what was requested",
                "   - Modifications that impact how existing features work in ways not mentioned in the request",
            ]
        ),
        exceptions=("Minor refactors directly related to requested changes are acceptable.",),
        additional_guide_for_agent="Compare the uncommitted diff and the request to ensure they match.",
    ),
    IssueIdentificationGuide(
        issue_code=IssueCode.DOCUMENTATION_IMPLEMENTATION_MISMATCH,
        guide="\n".join(
            [
                "- The implementation should follow, in this priority order: 1. the user's request, 2. documentation existing in the code base, 3. existing code around it, 4. general best practices and common sense",
                "- If the user's request conflicts with the state of documentation in the code base, the documentation in the code base should be updated to reflect the new user request.",
            ]
        ),
        examples=(
            "The docstring of a class or function does not match what the class or function implements.",
            "The repository contains a README.md file with instructions that are not adhered to by the code.",
            "The diff implements significant new functionality, but existing documentation within the repository is not updated.",
            "Inline comments are not updated even though functionality was changed by the diff.",
            "Documentation contains outdated code snippets or commands that need to be updated because of the changes made by the diff.",
        ),
        exceptions=("TODOs that are not implemented yet are not considered a documentation mismatch.",),
        additional_guide_for_agent="Look at code comments and READMEs in the diff or in existing code related to the diff.",
    ),
    IssueIdentificationGuide(
        issue_code=IssueCode.INCOMPLETE_INTEGRATION_WITH_EXISTING_CODE,
        guide="\n".join(
            [
                "- The diff should follow existing architectural and organizational patterns in the codebase:",
                "    - If the codebase uses a modular structure with separate files for classes/components, new classes should follow the same pattern",
                "    - If the codebase organizes code in specific directories (e.g., src/, components/, utils/), new code should be placed accordingly",
                "    - If the codebase uses specific import/export patterns (e.g., relative vs. absolute imports), new code should use the same patterns",
                "- The diff should integrate functionally with existing code by adding invocations, updating invocations, replacing code with newly defined functions or variables, removing duplicate code when a new piece replaces it, etc.",
                "- Prefer using existing library/dependency APIs over custom implementations when the library provides (or will provide) the needed functionality.",
            ]
        ),
        examples=(
            "The codebase uses absolute Python imports from the project root, but a new file uses relative imports.",
            "The codebase places classes into separate files under a source directory, but new classes are all added to an existing file.",
            "The diff implements a new function, but doesn't add any callsites for it",
            "A new optional parameter is added to a function to implement a requested feature, but existing callsites are not updated to make use of this parameter",
            "A named constant is introduced to replace a hard-coded inline literal, but existing code is not updated to make use of the new constant everywhere",
            "Custom code is added to implement functionality that an existing external library already provides or will provide in newer versions.",
        ),
        additional_guide_for_agent="\n".join(
            [
                "- Look at the existing code organization and architectural patterns",
                "- Check if new code follows the same structural patterns as existing code",
                "- Trace the links or identify the lack of them between the diff and existing code",
                "- Look at incomplete usage of new code",
            ]
        ),
    ),
    IssueIdentificationGuide(
        issue_code=IssueCode.USER_REQUEST_ARTIFACTS_LEFT_IN_CODE,
        guide="\n".join(
            [
                "- Comments should describe what the code does, not how it was changed.",
                "- Flag comments that reference the change process: '# Changed from X to Y', '# Updated to print less'",
                "- Flag comments that mention fixing or addressing issues: '# Fixed bug where...', '# This addresses...'",
                "- Flag documentation written in past tense about modifications",
                "- Acceptable comments explain current behavior without referencing changes:",
                "    - Acceptable: '# Multiply by 3x' instead of '# Reduced factor from 5x to 3x'",
                "    - Acceptable: '# Handle edge case' instead of '# Fixed edge case bug'",
            ]
        ),
        additional_guide_for_agent="Look at code comments and added documentation in the diff.",
    ),
    IssueIdentificationGuide(
        issue_code=IssueCode.POOR_NAMING,
        guide="\n".join(
            [
                "- File, class, function, function parameter, and constant names should follow the format and naming standards that are currently dominant in the code base (especially within the same file or folder).",
                "- In the absence of existing code, common naming standards for the given programming language should be used.",
                "- Function names should be descriptive of what the function does. A person reading the function name without seeing its implementation should be able to get a sense of its purpose.",
                "- If any function parameter is being mutated by the function, that fact should be made clear in the name of the parameter (e.g. by appending `_out` / `Out` to the name), unless it is clear that such name-based annotations would be against the existing naming style in the code base.",
                "- Note that we don't impose any specific criteria on the length of names. If the existing code base uses many abbreviated names, new code should follow that. Or if it uses a lot of long, verbose names, this similarly should be followed.",
                "- If a component's functionality is significantly changed, the name of the component should be updated to reflect the new functionality, if it is not already clear from the context.",
            ]
        ),
        exceptions=("Short names for local variables are usually okay.",),
        additional_guide_for_agent="\n".join(
            [
                "- Look at names that were added or names corresponding to updated code.",
                "- Understand existing codebase patterns.",
            ]
        ),
    ),
    IssueIdentificationGuide(
        issue_code=IssueCode.REPETITIVE_OR_DUPLICATE_CODE,
        guide="Repetitive or duplicate code.",
        examples=(
            "A non-trivial calculation or piece of logic is repeated in multiple places within a file.",
            "New code is introduced by the diff to accomplish a certain functionality, but there is an existing function in the code base that already implements the same functionality, or could be easily generalized to accomplish the desired functionality.",
            "A file is duplicated (make exceptions for cases where duplication may be necessary such as test files).",
            "A significant amount of code is introduced which duplicates functionality from standard or well-known libraries.",
            "Multiple functions format or build the same string or data structure in the same way without using a shared helper function.",
        ),
        exceptions=(
            "Do not flag duplication between legacy and new implementations when the codebase is clearly undergoing a migration or maintaining multiple versions for compatibility.",
            "Do not flag duplication across different architectural layers or modules when the duplication serves to maintain proper separation of concerns.",
        ),
        additional_guide_for_agent="\n".join(
            [
                "- Look at repetition in the diff or duplication between the diff and existing code in the codebase.",
                "- Look at incomplete usage of new code",
                "- Understand existing codebase patterns.",
            ]
        ),
    ),
    IssueIdentificationGuide(
        issue_code=IssueCode.REFACTORING_NEEDED,
        guide="\n".join(
            [
                "- Functions that have gotten long (> 50 lines) and are mixing multiple concerns and/or combining several different steps should be broken up. (Typically by using helper functions and/or separate classes to encapsulate individual concerns.)",
                "- Classes or files that are combining different concerns should be broken up, such that each class / file only deals with one primary concern.",
                "    - Note: we don't impose any minimal or maximal length on a class or file. Classes and files are ok to be long, as long as they only deal with a single concern.",
            ]
        ),
        examples=(
            "New functionality that is orthogonal to the existing functionality in a function is inserted into the existing function's body instead of being separated out into its own function.",
            "A class mixes two different use cases that could be separated into two classes.",
        ),
        additional_guide_for_agent="\n".join(
            [
                "- Look at the scope and length of components of the diff or code affected by the diff.",
                "- Look at incomplete usage of new code.",
                "- Understand existing codebase patterns.",
            ]
        ),
    ),
    IssueIdentificationGuide(
        issue_code=IssueCode.TEST_COVERAGE,
        guide="\n".join(
            [
                "- If the diff introduces significant new functionality, and the code base has existing unit and/or integration tests, new tests should be added to cover the new functionality.",
                "- If the diff changes the behavior of existing functionality that is covered by automated tests, those tests should be updated to reflect the new behavior.",
                "- If the diff contains a bug fix, and the code base has existing unit and/or integration tests, a regression test should be added for the bug.",
            ]
        ),
        exceptions=(
            "Syntactical or logical issues in tests will be raised in other issue types and do not belong in this category.",
        ),
        additional_guide_for_agent="\n".join(
            [
                "- Look at the diff and tests for it or tests affected by it or missing tests.",
                "- Understand existing codebase patterns.",
                "- Run code but this may not always be a viable option or may surface irrelevant issues.",
            ]
        ),
    ),
    IssueIdentificationGuide(
        issue_code=IssueCode.RESOURCE_LEAKAGE,
        guide="\n".join(
            [
                "- Focus on system resources that require explicit cleanup: file handles, network connections, database connections, memory allocations, and similar OS-level resources.",
                "- These resources must be reliably freed even if exceptions occur.",
                "- For these system resources, cleanup should use try/finally blocks, context managers (with statements), or RAII patterns.",
                "- Also look for reference management issues: objects being cleaned up while still holding references elsewhere, or cleanup operations (like garbage collection) called before removing all references to the object.",
            ]
        ),
        examples=(
            "A file or socket connection is opened but not reliably closed.",
            "A database transaction is started but not committed or rolled back in all code paths.",
            "Memory is allocated but not freed (in languages with manual memory management).",
            "An object's cleanup method triggers garbage collection while the object is still referenced in a global data structure, preventing proper cleanup.",
        ),
        exceptions=(
            "Animation loops, timers, and intervals that are controlled by boolean flags or cleared by ID are not resource leaks if they have proper stop mechanisms.",
            "Event listeners that are meant to persist for the lifetime of the application.",
            "Resources that are automatically cleaned up by garbage collection (unless they hold system resources).",
        ),
        additional_guide_for_agent="Carefully examine the diff or code affected by newly added code.",
    ),
    IssueIdentificationGuide(
        issue_code=IssueCode.DEPENDENCY_MANAGEMENT,
        guide="\n".join(
            [
                "- Check all import statements in new or modified files. If new code imports a library or package that is not part of the language's standard library, verify that the dependency is listed in the repository's dependency/requirement files (e.g., requirements.txt, pyproject.toml, package.json, Gemfile, etc.).",
                "- If the diff removes the last remaining use of an external library or package, the dependency and/or requirement files in the repository should be updated to no longer include the library.",
                "- If the codebase uses a dependency for some functionality, the diff should avoid introducing other packages that provide the same functionality, unless there is a good reason to do so (e.g. the new package is significantly better maintained, has better performance, or is more secure).",
            ]
        ),
        exceptions=("Do not raise issues related to package versions or pinning unless it is a critical issue.",),
        additional_guide_for_agent="\n".join(
            [
                "- Look at the diff and dependency management files for issues.",
                "- Understand existing codebase patterns.",
                "- Carefully check import statements at the top of new or modified files.",
            ]
        ),
    ),
    IssueIdentificationGuide(
        issue_code=IssueCode.INSECURE_CODE,
        guide="\n".join(
            [
                "- Look for hard-coded secrets such as API keys, passwords, tokens, or credentials in the diff.",
                "- Check for variable names containing: 'token', 'key', 'secret', 'password', 'credential', 'auth'",
                "- Look for string literals that appear to be:",
                "    - API keys or tokens (long alphanumeric strings, often 20+ characters)",
                "    - Hexadecimal strings that could be tokens or keys",
                "    - URLs with embedded credentials (e.g., 'https://user:password@host')",
                "    - Connection strings with passwords",
                "- Flag any credentials or secrets that should be loaded from environment variables or configuration files instead.",
            ]
        ),
        examples=(
            "A variable named `api_key` or `auth_token` is assigned a hard-coded string value.",
            "A connection string contains a hard-coded password.",
            "A long hexadecimal string is assigned to a variable with 'token' in its name.",
            "An API request includes a hard-coded authentication header value.",
        ),
        additional_guide_for_agent="Carefully examine the diff for any string literals that might be secrets, especially those assigned to variables with security-related names.",
    ),
    IssueIdentificationGuide(
        issue_code=IssueCode.FAILS_SILENTLY,
        guide="Code that fails silently is code that ignores errors without reporting them.",
        examples=(
            "The code indiscriminately captures exceptions of all types (e.g. Exception) and continues execution without taking any action to handle the error.",
            "The return value of a function that returns an error value in case of a failure is not checked by the caller.",
        ),
        exceptions=(
            "There are certain cases where broad exception handlers are acceptable, such as in an executor class or in a main loop that iterates over several tasks. Such cases should still properly log and report the errors.",
            "Do not raise issues related to potential program crashes.",
        ),
        additional_guide_for_agent="Carefully examine the diff.",
    ),
    IssueIdentificationGuide(
        issue_code=IssueCode.INSTRUCTION_FILE_DISOBEYED,
        guide="Explicit instructions in files such as .claude.md, CLAUDE.md, and AGENTS.md MUST be obeyed.",
        examples=(
            "CLAUDE.md requests the use of single quotes only, but double quotes are used.",
            "AGENTS.md requests that new versions be created on every database update, but a database entry is modified directly.",
            ".claude.md says to always run the tests after making changes, but the agent did not run the tests.",
        ),
        exceptions=(
            "Instructions in the closest file _above_ a location take precedence. For example, when considering a file foo/bar.py, foo/CLAUDE.md takes precedence over CLAUDE.md.",
            "Instructions only apply to the subtree below the file. For example, when considering a file foo/bar.py, foo/baz/CLAUDE.md does not apply.",
            "Applicable instructions should ONLY be contravened in the case of explicit user request--but if the user does explicitly request something counter to the instruction files, this should not be reported as a disobeyed instruction file.",
        ),
        additional_guide_for_agent="Cross-check ALL instructions in ALL instruction files against the diff contents.",
    ),
    IssueIdentificationGuide(
        issue_code=IssueCode.LOGIC_ERROR,
        guide="\n".join(
            [
                "- Logic errors are flaws in the reasoning or flow of the code that would cause incorrect behavior.",
                "- Look for: off-by-one errors in loops or array indexing, incorrect conditional logic (wrong operators, inverted conditions), variable assignments that overwrite needed values, incorrect order of operations, missing or incorrect loop termination conditions, algorithms that don't match their intended purpose.",
                "- Look for missing, incorrect, or incomplete parameters to function/API calls that will cause the function to behave differently than intended (e.g., missing event masks, wrong flags, omitted required options).",
                "- Pay special attention to control flow issues: early returns or breaks that prevent intended functionality from executing, functions that exit before completing their stated purpose, conditions that prevent code paths from being reached when they should be.",
                "- Do not flag issues that are not clearly incorrect, for example it's possible code is implemented in a suboptimal way, this is not an issue unless it is explicitly stated that the code should be optimal or implemented in a certain way.",
            ]
        ),
    ),
    IssueIdentificationGuide(
        issue_code=IssueCode.RUNTIME_ERROR_RISK,
        guide="\n".join(
            [
                "- Code patterns that are very likely to cause runtime errors during execution.",
                "- Check for version compatibility issues: usage of function parameters, APIs, or language features that are only available in specific versions of the language, standard library, or external dependencies (e.g., a keyword argument added in Python 3.10 will cause TypeError on Python 3.8/3.9).",
                "- Look for: potential null/None pointer dereferences, array/list access with potentially invalid indices, division by zero possibilities, file operations without existence checks, network/IO operations without timeout or error handling, infinite loop conditions, memory allocation issues.",
                "- Check string encoding/decoding operations: calls to .encode() or .decode() without error handling (try/except or 'errors' parameter) that could raise UnicodeEncodeError or UnicodeDecodeError, especially when processing untrusted or streamed data.",
                "- Look for operations with global side effects that could cause problems: os.chdir() without proper restoration, modifying global state in ways that affect other code, operations that are not thread-safe when concurrency is present.",
                "- Only flag issues where there is clear evidence the code will fail or cause serious problems. Avoid speculating about potential issues in well-established language patterns or standard library usage.",
            ]
        ),
    ),
    IssueIdentificationGuide(
        issue_code=IssueCode.INCORRECT_ALGORITHM,
        guide="\n".join(
            [
                "- Code that implements an algorithm incorrectly for its stated purpose.",
                "- Look for: sorting algorithms with wrong comparison logic, search algorithms with incorrect termination, mathematical calculations with wrong formulas, data structure operations that don't maintain invariants, algorithms that don't handle edge cases (empty inputs, single elements).",
                "- Only flag issues that are clearly incorrect for the stated purpose of the algorithm, and describe the problem and correction in detail.",
            ]
        ),
    ),
    IssueIdentificationGuide(
        issue_code=IssueCode.ERROR_HANDLING_MISSING,
        guide="\n".join(
            [
                "- Missing error handling for operations that could reasonably fail.",
                "- Look for: file I/O without exception handling, network requests without timeout/retry logic, user input processing without validation, external API calls without error checking, database operations without transaction handling.",
                "- Only flag issues that are clearly incorrect, and avoid flagging issues where it is not a big problem (e.g. file I/O in a script may not need flagging while missing error handling for file I/O in a long running or production systems should have error handling).",
            ]
        ),
    ),
    IssueIdentificationGuide(
        issue_code=IssueCode.ASYNC_CORRECTNESS,
        guide="\n".join(
            [
                "- Issues specific to asynchronous or concurrent code correctness.",
                "- Look for: missing await keywords on functions that are clearly async (defined with 'async def' or returning coroutines/Promises), improper async context manager usage, race conditions in async code, deadlock potential, shared state access without proper synchronization.",
                "- For threading issues: threads or background tasks that are created but never started, joins without corresponding starts.",
                "- Be careful not to flag decorators or wrappers as requiring await unless you can verify they actually make the function async. Only flag clear cases where an async function is called without await or a thread/task is created but never started.",
            ]
        ),
    ),
    IssueIdentificationGuide(
        issue_code=IssueCode.TYPE_SAFETY_VIOLATION,
        guide="\n".join(
            [
                "- Code that violates type safety expectations or could cause type-related runtime errors.",
                "- Look for: incorrect type assumptions, missing type checks before operations, unsafe type casting, attribute access on potentially None values.",
                "- Check for return type violations: functions that return values inconsistent with their declared return type annotations (e.g., returning None when the type annotation specifies a non-optional type, returning wrong tuple element types).",
            ]
        ),
    ),
    IssueIdentificationGuide(
        issue_code=IssueCode.CORRECTNESS_SYNTAX_ISSUES,
        guide="\n".join(
            [
                "- The diff should not contain any syntax errors that would prevent the code from running.",
                "- CAREFULLY CHECK INDENTATION: In Python and other indentation-sensitive languages, verify that all function definitions, class definitions, and code blocks maintain proper indentation levels. Dedenting a function body to the module level or similar indentation errors are critical syntax issues.",
                "- Look for: broken indentation that would cause syntax errors, missing or mismatched brackets/braces/parentheses, references to files/classes/functions that don't exist, removal of code that is still being referenced elsewhere.",
                "- Check function signatures match their usage: if a function is modified to return different values (e.g., a single value vs. a tuple), all call sites must be updated accordingly.",
            ]
        ),
        examples=(
            "The diff breaks the indentation of a Python function or class, dedenting it incorrectly.",
            "Code references a file, class or function that does not exist, or removes a file, class or function that is definitely still being referenced.",
            "A function is changed to return a tuple of two values, but existing callers still expect only a single return value.",
            "A function's return statement is removed but callers still expect a return value.",
        ),
    ),
    IssueIdentificationGuide(
        issue_code=IssueCode.MISLEADING_BEHAVIOR,
        guide="\n".join(
            [
                "The agent did something misleading in the conversation history.",
                "When writing your response, phrase it collaboratively rather than combatively.",
                "The response will be given as feedback to the agent, so it should avoid making the agent defensive by assuming good intentions when possible.",
                "The collaborative tone shouldn't make you more lenient--you should not hesitate to point out behavior that might mislead the user.",
                "However, if the agent did something misleading, but then corrected its mistake, such that the final result shown to the user was not misleading, you should not point out the original mistake.",
                "You should also not point out the behavior if the user is clearly aware of it; for example, you should not flag misleading behavior if the user asked the agent to mark something as done when it was not.",
                "Also do not flag all behavior that doesn't match the user's request as misleading; for example, you should not flag misleading behavior if the agent makes changes the user didn't ask for, but the changes aren't themselves misleading, like a refactoring that improves the code.",
                "In addition, you should not consider checking off tasks on the TODO list as potentially misleading; the agent is intended to check off a TODO whenever it is done considering the task for that turn, which may be because it has not completed the task but needs more information to proceed.",
                "When writing the description, you don't need to explain why the behavior was misleading--just describe the behavior itself.",
                "Any self-identification made by the agent in the conversation history should be assumed to be accurate.",
            ]
        ),
        examples=(
            "The agent can't run a test file, so it checks that the test file has valid syntax instead, and proceeds as though the tests passed.",
            "The agent claims in a message to have achieved its original goal when it clearly has not.",
            "The agent uses fake data when it is unable to get real data, e.g. as a 'fallback'.",
        ),
    ),
    IssueIdentificationGuide(
        issue_code=IssueCode.INSTRUCTION_TO_SAVE,
        guide="The user gives guidance or feedback to the agent about general code style, their intent for the project, or anything else that is relevant beyond the scope of the current task.",
        examples=(
            "The user tells the agent to move all the imports to the top of the file, and there is no preexisting instruction in the instruction file to have all imports at the top.",
            "The user asks the agent to avoid importing a library because they need image builds to be fast, and the project specification does not already mention that the application will run in a container under conditions where speed of builds could be reasonably considered to be a priority.",
            "The user provides an instruction that contradicts something in an AGENTS.md file",
        ),
    ),
    IssueIdentificationGuide(
        issue_code=IssueCode.ABSTRACTION_VIOLATION,
        guide="\n".join(
            [
                "- Code that breaks established abstraction boundaries within the codebase.",
                "- Look for:",
                "    - Direct access to internal data structures of classes/modules that should be encapsulated",
                "    - Bypassing public APIs to manipulate state or access internal functionality",
                "    - Mixing of concerns that should be separated by layers or modules",
                "    - Violating private vs. public interfaces (e.g., accessing private attributes or methods from outside their defining class/module)",
            ]
        ),
        examples=(
            "A Python function directly accesses a private attribute, variable or function (prefixed with an underscore) from a different class or file.",
            "A module modifies the internal state of another module directly instead of using and/or adding public API functions.",
        ),
        exceptions=("Unit tests that need to access internal state for verification purposes.",),
    ),
)

ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE: dict[IssueCode, IssueIdentificationGuide] = {
    guide.issue_code: guide for guide in ISSUE_IDENTIFICATION_GUIDES
}


ISSUE_CODES_FOR_BATCHED_COMMIT_CHECK: tuple[IssueCode, ...] = (
    IssueCode.COMMIT_MESSAGE_MISMATCH,
    IssueCode.DOCUMENTATION_IMPLEMENTATION_MISMATCH,
    IssueCode.INCOMPLETE_INTEGRATION_WITH_EXISTING_CODE,
    IssueCode.USER_REQUEST_ARTIFACTS_LEFT_IN_CODE,
    IssueCode.POOR_NAMING,
    IssueCode.REPETITIVE_OR_DUPLICATE_CODE,
    IssueCode.REFACTORING_NEEDED,
    IssueCode.TEST_COVERAGE,
    IssueCode.RESOURCE_LEAKAGE,
    IssueCode.DEPENDENCY_MANAGEMENT,
    IssueCode.INSECURE_CODE,
    IssueCode.FAILS_SILENTLY,
    IssueCode.INSTRUCTION_FILE_DISOBEYED,
    IssueCode.ABSTRACTION_VIOLATION,
)

ISSUE_CODES_FOR_CORRECTNESS_CHECK: tuple[IssueCode, ...] = (
    IssueCode.LOGIC_ERROR,
    IssueCode.RUNTIME_ERROR_RISK,
    IssueCode.INCORRECT_ALGORITHM,
    IssueCode.ERROR_HANDLING_MISSING,
    IssueCode.ASYNC_CORRECTNESS,
    IssueCode.TYPE_SAFETY_VIOLATION,
    IssueCode.CORRECTNESS_SYNTAX_ISSUES,
)

ISSUE_CODES_FOR_CONVERSATION_HISTORY_CHECK: tuple[IssueCode, ...] = (
    IssueCode.MISLEADING_BEHAVIOR,
    IssueCode.INSTRUCTION_FILE_DISOBEYED,
    IssueCode.INSTRUCTION_TO_SAVE,
)


def apply_custom_guides(
    guides_by_code: dict[IssueCode, IssueIdentificationGuide],
    custom_config: CustomGuidesConfig | None,
) -> dict[IssueCode, IssueIdentificationGuide]:
    if custom_config is None or not custom_config.guides:
        return guides_by_code

    result = dict(guides_by_code)
    for issue_code_str, custom in custom_config.guides.items():
        issue_code = IssueCode(issue_code_str)
        built_in = result[issue_code]

        match custom.mode:
            case GuideMode.PREFIX:
                merged_guide = custom.guide + "\n" + built_in.guide
            case GuideMode.SUFFIX:
                merged_guide = built_in.guide + "\n" + custom.guide
            case GuideMode.REPLACE:
                merged_guide = custom.guide

        result[issue_code] = IssueIdentificationGuide(
            issue_code=issue_code,
            guide=merged_guide,
            additional_guide_for_agent=built_in.additional_guide_for_agent,
            examples=built_in.examples,
            exceptions=built_in.exceptions,
        )

    return result
