"""
Custom guide parsing and merging logic for user-defined issue prompts.

Users can customize issue identification prompts by creating markdown files
in a configured directory (e.g., .vet/custom_guides/). Each file corresponds
to one issue code and can specify prefix, suffix, or replace modifications.
"""

from pathlib import Path

from loguru import logger

from vet.imbue_core.data_types import IssueCode
from vet.imbue_core.pydantic_serialization import SerializableModel


class CustomGuideOverride(SerializableModel):
    """
    User's custom guide modifications for a specific issue code.

    Represents the parsed content from a markdown file like:
    ```markdown
    # vet_custom_guideline_prefix
    Content to prepend...

    # vet_custom_guideline_suffix
    Content to append...

    # vet_custom_guideline_replace
    Complete replacement...
    ```
    """

    issue_code: IssueCode
    prefix: str | None = None
    suffix: str | None = None
    replace: str | None = None
    source_file: Path | None = None  # For error messages

    def has_conflict(self) -> bool:
        """Check if replace is used with prefix/suffix (invalid combination)."""
        return self.replace is not None and (self.prefix is not None or self.suffix is not None)

    def is_empty(self) -> bool:
        """Check if this override has no actual content."""
        return self.prefix is None and self.suffix is None and self.replace is None


def parse_custom_guide_markdown(file_path: Path) -> CustomGuideOverride | None:
    """
    Parse a markdown file containing custom guide sections.

    Expected format:
        Filename: {issue_code}.md
        Sections (all optional):
        - # vet_custom_guideline_prefix
        - # vet_custom_guideline_suffix
        - # vet_custom_guideline_replace

    Args:
        file_path: Path to markdown file (filename is issue code)

    Returns:
        CustomGuideOverride with parsed sections, or None if invalid issue code

    Raises:
        ValueError: If file reading or parsing fails
    """
    # Extract issue code from filename
    issue_code_str = file_path.stem

    # Check if it's a valid issue code (directly against enum values)
    valid_issue_codes = {code.value for code in IssueCode}
    if issue_code_str not in valid_issue_codes:
        logger.warning(
            "Invalid issue code '{}' in filename: {}. Skipping this file. Valid codes: {}",
            issue_code_str,
            file_path.name,
            ", ".join(sorted(valid_issue_codes)),
        )
        return None

    issue_code = IssueCode(issue_code_str)

    # Read file content
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        raise ValueError(f"Failed to read file {file_path}: {e}") from e

    # Parse sections
    sections: dict[str, str] = {}
    current_section: str | None = None
    current_content: list[str] = []

    for line in content.split("\n"):
        stripped = line.strip()

        # Check for section headers (exact match, case-sensitive)
        if stripped == "# vet_custom_guideline_prefix":
            # Save previous section if any
            if current_section and current_content:
                sections[current_section] = "\n".join(current_content).strip()
            current_section = "prefix"
            current_content = []

        elif stripped == "# vet_custom_guideline_suffix":
            if current_section and current_content:
                sections[current_section] = "\n".join(current_content).strip()
            current_section = "suffix"
            current_content = []

        elif stripped == "# vet_custom_guideline_replace":
            if current_section and current_content:
                sections[current_section] = "\n".join(current_content).strip()
            current_section = "replace"
            current_content = []

        else:
            # Accumulate content for current section
            if current_section is not None:
                current_content.append(line)

    # Save final section
    if current_section and current_content:
        sections[current_section] = "\n".join(current_content).strip()

    # Build override object (empty strings become None)
    return CustomGuideOverride(
        issue_code=issue_code,
        prefix=sections.get("prefix") or None,
        suffix=sections.get("suffix") or None,
        replace=sections.get("replace") or None,
        source_file=file_path,
    )


def load_custom_guides_from_directory(directory: Path) -> dict[IssueCode, CustomGuideOverride]:
    """
    Load all custom guide markdown files from a directory.

    Args:
        directory: Path to directory containing {issue_code}.md files

    Returns:
        Dictionary mapping IssueCode to CustomGuideOverride (empty if directory doesn't exist)

    Raises:
        ValueError: If parsing fails or duplicates found
    """
    # If directory doesn't exist, return empty dict (no custom guides)
    if not directory.exists():
        logger.debug("Custom guides directory does not exist: {}", directory)
        return {}

    if not directory.is_dir():
        logger.warning("Custom guides path is not a directory: {}", directory)
        return {}

    custom_guides: dict[IssueCode, CustomGuideOverride] = {}

    # Find all markdown files
    md_files = list(directory.glob("*.md"))

    if not md_files:
        logger.debug("No .md files found in custom guides directory: {}", directory)
        return {}

    for md_file in md_files:
        try:
            override = parse_custom_guide_markdown(md_file)

            # Skip if invalid issue code (returns None)
            if override is None:
                continue

            # Only add if at least one section is defined
            if not override.is_empty():
                custom_guides[override.issue_code] = override
            else:
                logger.debug("Skipping {}: all sections are empty", md_file.name)

        except Exception as e:
            logger.error("Failed to parse {}: {}. Skipping this file.", md_file.name, e)
            continue

    if custom_guides:
        logger.info("Loaded {} custom guide override(s) from {}", len(custom_guides), directory)

    return custom_guides


def validate_custom_guides(custom_guides: dict[IssueCode, CustomGuideOverride]) -> None:
    """
    Validate custom guides and warn about conflicts.

    Checks for:
    - Using 'replace' with 'prefix' or 'suffix' (replace should be independent)

    Args:
        custom_guides: Dictionary of custom guide overrides to validate

    Logs warnings for conflicts but does not raise errors.
    Replace mode takes precedence and prefix/suffix are ignored.
    """
    for issue_code, override in custom_guides.items():
        if override.has_conflict():
            logger.warning(
                "Issue '{}': conflicting 'replace' with 'prefix'/'suffix', ignoring prefix/suffix: {}",
                issue_code,
                override.source_file,
            )
