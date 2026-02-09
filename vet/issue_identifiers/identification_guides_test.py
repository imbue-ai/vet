"""Tests for identification guide merging with custom overrides."""

from __future__ import annotations

from pathlib import Path

from vet.imbue_core.data_types import IssueCode
from vet.issue_identifiers.custom_guides import CustomGuideOverride
from vet.issue_identifiers.identification_guides import (
    ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE,
    IssueIdentificationGuide,
    build_merged_guides,
    merge_guide_with_custom,
)


def test_merge_guide_with_custom_none_returns_default() -> None:
    """Test that passing None as override returns default unchanged."""
    default_guide = IssueIdentificationGuide(
        issue_code=IssueCode.LOGIC_ERROR,
        guide="Default guide text",
        examples=("Example 1", "Example 2"),
        exceptions=("Exception 1",),
    )

    result = merge_guide_with_custom(default_guide, None)

    assert result == default_guide
    assert result.guide == "Default guide text"
    assert result.examples == ("Example 1", "Example 2")
    assert result.exceptions == ("Exception 1",)


def test_merge_guide_with_custom_prefix_only(tmp_path: Path) -> None:
    """Test merging with prefix only."""
    default_guide = IssueIdentificationGuide(
        issue_code=IssueCode.LOGIC_ERROR,
        guide="Default guide text",
        examples=("Example 1",),
        exceptions=("Exception 1",),
    )

    custom_override = CustomGuideOverride(
        issue_code=IssueCode.LOGIC_ERROR,
        prefix="Custom prefix\nWith multiple lines",
        source_file=tmp_path / "test.md",
    )

    result = merge_guide_with_custom(default_guide, custom_override)

    assert result.issue_code == IssueCode.LOGIC_ERROR
    assert result.guide == "Custom prefix\nWith multiple lines\n\nDefault guide text"
    # Examples and exceptions should be preserved
    assert result.examples == ("Example 1",)
    assert result.exceptions == ("Exception 1",)


def test_merge_guide_with_custom_suffix_only(tmp_path: Path) -> None:
    """Test merging with suffix only."""
    default_guide = IssueIdentificationGuide(
        issue_code=IssueCode.INSECURE_CODE,
        guide="Default guide text",
        examples=("Example 1",),
    )

    custom_override = CustomGuideOverride(
        issue_code=IssueCode.INSECURE_CODE,
        suffix="Custom suffix\nAdditional notes",
        source_file=tmp_path / "test.md",
    )

    result = merge_guide_with_custom(default_guide, custom_override)

    assert result.guide == "Default guide text\n\nCustom suffix\nAdditional notes"
    assert result.examples == ("Example 1",)


def test_merge_guide_with_custom_prefix_and_suffix(tmp_path: Path) -> None:
    """Test merging with both prefix and suffix."""
    default_guide = IssueIdentificationGuide(
        issue_code=IssueCode.TEST_COVERAGE,
        guide="Default guide text",
    )

    custom_override = CustomGuideOverride(
        issue_code=IssueCode.TEST_COVERAGE,
        prefix="IMPORTANT:",
        suffix="Remember to profile first!",
        source_file=tmp_path / "test.md",
    )

    result = merge_guide_with_custom(default_guide, custom_override)

    assert result.guide == "IMPORTANT:\n\nDefault guide text\n\nRemember to profile first!"


def test_merge_guide_with_custom_replace_only(tmp_path: Path) -> None:
    """Test merging with replace mode."""
    default_guide = IssueIdentificationGuide(
        issue_code=IssueCode.LOGIC_ERROR,
        guide="Default guide text",
        examples=("Example 1", "Example 2"),
        exceptions=("Exception 1",),
        additional_guide_for_agent="Agent guidance",
    )

    custom_override = CustomGuideOverride(
        issue_code=IssueCode.LOGIC_ERROR,
        replace="Completely new guide text",
        source_file=tmp_path / "test.md",
    )

    result = merge_guide_with_custom(default_guide, custom_override)

    assert result.guide == "Completely new guide text"
    # Examples, exceptions, and additional_guide_for_agent should be preserved
    assert result.examples == ("Example 1", "Example 2")
    assert result.exceptions == ("Exception 1",)
    assert result.additional_guide_for_agent == "Agent guidance"


def test_merge_guide_with_custom_replace_takes_precedence_over_prefix(tmp_path: Path) -> None:
    """Test that replace mode takes precedence when both replace and prefix are present."""
    default_guide = IssueIdentificationGuide(
        issue_code=IssueCode.LOGIC_ERROR,
        guide="Default guide text",
    )

    custom_override = CustomGuideOverride(
        issue_code=IssueCode.LOGIC_ERROR,
        prefix="This should be ignored",
        replace="Replace text",
        source_file=tmp_path / "test.md",
    )

    result = merge_guide_with_custom(default_guide, custom_override)

    # Only replace should be applied, prefix should be ignored
    assert result.guide == "Replace text"


def test_merge_guide_with_custom_replace_takes_precedence_over_suffix(tmp_path: Path) -> None:
    """Test that replace mode takes precedence when both replace and suffix are present."""
    default_guide = IssueIdentificationGuide(
        issue_code=IssueCode.LOGIC_ERROR,
        guide="Default guide text",
    )

    custom_override = CustomGuideOverride(
        issue_code=IssueCode.LOGIC_ERROR,
        suffix="This should be ignored",
        replace="Replace text",
        source_file=tmp_path / "test.md",
    )

    result = merge_guide_with_custom(default_guide, custom_override)

    # Only replace should be applied, suffix should be ignored
    assert result.guide == "Replace text"


def test_merge_guide_with_custom_replace_takes_precedence_over_both(tmp_path: Path) -> None:
    """Test that replace mode takes precedence when all three are present."""
    default_guide = IssueIdentificationGuide(
        issue_code=IssueCode.LOGIC_ERROR,
        guide="Default guide text",
    )

    custom_override = CustomGuideOverride(
        issue_code=IssueCode.LOGIC_ERROR,
        prefix="Ignored prefix",
        suffix="Ignored suffix",
        replace="Replace text wins",
        source_file=tmp_path / "test.md",
    )

    result = merge_guide_with_custom(default_guide, custom_override)

    assert result.guide == "Replace text wins"


def test_merge_guide_with_custom_preserves_whitespace(tmp_path: Path) -> None:
    """Test that whitespace in custom content is preserved (after strip on each section)."""
    default_guide = IssueIdentificationGuide(
        issue_code=IssueCode.LOGIC_ERROR,
        guide="Default",
    )

    custom_override = CustomGuideOverride(
        issue_code=IssueCode.LOGIC_ERROR,
        prefix="  Prefix with spaces  ",  # Will be stripped by merge logic
        suffix="  Suffix with spaces  ",
        source_file=tmp_path / "test.md",
    )

    result = merge_guide_with_custom(default_guide, custom_override)

    # The merge logic calls .strip() on prefix and suffix
    assert result.guide == "Prefix with spaces\n\nDefault\n\nSuffix with spaces"


def test_build_merged_guides_empty_overrides() -> None:
    """Test building merged guides with no custom overrides."""
    result = build_merged_guides({})

    # Should return all default guides unchanged
    assert len(result) == len(ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE)
    for code, guide in result.items():
        assert guide == ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE[code]


def test_build_merged_guides_single_override(tmp_path: Path) -> None:
    """Test building merged guides with a single custom override."""
    custom_overrides = {
        IssueCode.LOGIC_ERROR: CustomGuideOverride(
            issue_code=IssueCode.LOGIC_ERROR,
            prefix="Custom prefix",
            source_file=tmp_path / "logic_error.md",
        )
    }

    result = build_merged_guides(custom_overrides)

    # Should have all guides
    assert len(result) == len(ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE)

    # LOGIC_ERROR should be merged
    logic_error_guide = result[IssueCode.LOGIC_ERROR]
    assert logic_error_guide.guide.startswith("Custom prefix\n\n")

    # Other guides should remain unchanged
    for code, guide in result.items():
        if code != IssueCode.LOGIC_ERROR:
            assert guide == ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE[code]


def test_build_merged_guides_multiple_overrides(tmp_path: Path) -> None:
    """Test building merged guides with multiple custom overrides."""
    custom_overrides = {
        IssueCode.LOGIC_ERROR: CustomGuideOverride(
            issue_code=IssueCode.LOGIC_ERROR,
            prefix="Logic prefix",
            source_file=tmp_path / "logic_error.md",
        ),
        IssueCode.INSECURE_CODE: CustomGuideOverride(
            issue_code=IssueCode.INSECURE_CODE,
            suffix="Security suffix",
            source_file=tmp_path / "insecure_code.md",
        ),
        IssueCode.TEST_COVERAGE: CustomGuideOverride(
            issue_code=IssueCode.TEST_COVERAGE,
            replace="Performance replace",
            source_file=tmp_path / "test_coverage.md",
        ),
    }

    result = build_merged_guides(custom_overrides)

    # Check that all three were merged correctly
    assert result[IssueCode.LOGIC_ERROR].guide.startswith("Logic prefix\n\n")
    assert result[IssueCode.INSECURE_CODE].guide.endswith("\n\nSecurity suffix")
    assert result[IssueCode.TEST_COVERAGE].guide == "Performance replace"

    # Check that non-overridden guides remain unchanged
    for code, guide in result.items():
        if code not in custom_overrides:
            assert guide == ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE[code]


def test_build_merged_guides_preserves_all_guide_fields(tmp_path: Path) -> None:
    """Test that merging preserves all fields of IssueIdentificationGuide."""
    # Get a guide that has all fields populated
    original_guide = ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE[IssueCode.COMMIT_MESSAGE_MISMATCH]

    custom_overrides = {
        IssueCode.COMMIT_MESSAGE_MISMATCH: CustomGuideOverride(
            issue_code=IssueCode.COMMIT_MESSAGE_MISMATCH,
            prefix="Custom prefix",
            source_file=tmp_path / "commit_message_mismatch.md",
        )
    }

    result = build_merged_guides(custom_overrides)
    merged_guide = result[IssueCode.COMMIT_MESSAGE_MISMATCH]

    # Check that only 'guide' was modified
    assert merged_guide.guide.startswith("Custom prefix\n\n")
    assert merged_guide.guide != original_guide.guide

    # Check that other fields are preserved
    assert merged_guide.issue_code == original_guide.issue_code
    assert merged_guide.examples == original_guide.examples
    assert merged_guide.exceptions == original_guide.exceptions
    assert merged_guide.additional_guide_for_agent == original_guide.additional_guide_for_agent


def test_merge_guide_with_custom_empty_strings_become_none(tmp_path: Path) -> None:
    """Test that empty string content is treated as None."""
    default_guide = IssueIdentificationGuide(
        issue_code=IssueCode.LOGIC_ERROR,
        guide="Default",
    )

    # CustomGuideOverride with empty strings should be treated as None
    # This is handled by parse_custom_guide_markdown which returns None for empty strings
    custom_override = CustomGuideOverride(
        issue_code=IssueCode.LOGIC_ERROR,
        prefix=None,  # Parser would return None for empty sections
        suffix=None,
        source_file=tmp_path / "test.md",
    )

    result = merge_guide_with_custom(default_guide, custom_override)

    # Should just return default since no prefix/suffix
    assert result.guide == "Default"


def test_merge_guide_with_custom_multiline_guide_text(tmp_path: Path) -> None:
    """Test merging with multiline guide text."""
    default_guide = IssueIdentificationGuide(
        issue_code=IssueCode.LOGIC_ERROR,
        guide="Line 1 of default\nLine 2 of default\nLine 3 of default",
    )

    custom_override = CustomGuideOverride(
        issue_code=IssueCode.LOGIC_ERROR,
        prefix="Prefix line 1\nPrefix line 2",
        suffix="Suffix line 1\nSuffix line 2",
        source_file=tmp_path / "test.md",
    )

    result = merge_guide_with_custom(default_guide, custom_override)

    expected = "Prefix line 1\nPrefix line 2\n\nLine 1 of default\nLine 2 of default\nLine 3 of default\n\nSuffix line 1\nSuffix line 2"
    assert result.guide == expected


def test_build_merged_guides_does_not_modify_original_defaults() -> None:
    """Test that building merged guides doesn't modify the original default guides."""
    # Get original guide
    original_guide = ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE[IssueCode.LOGIC_ERROR]
    original_guide_text = original_guide.guide

    custom_overrides = {
        IssueCode.LOGIC_ERROR: CustomGuideOverride(
            issue_code=IssueCode.LOGIC_ERROR,
            prefix="Prefix",
            source_file=Path("/tmp/test.md"),
        )
    }

    # Build merged guides
    merged_guides = build_merged_guides(custom_overrides)

    # Check that original is unchanged
    assert ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE[IssueCode.LOGIC_ERROR].guide == original_guide_text
    # Check that merged is different
    assert merged_guides[IssueCode.LOGIC_ERROR].guide != original_guide_text
    assert merged_guides[IssueCode.LOGIC_ERROR].guide.startswith("Prefix\n\n")
