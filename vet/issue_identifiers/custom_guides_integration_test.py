"""Integration tests for custom guides end-to-end flow."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from vet.cli.config.loader import get_custom_guides_directories
from vet.imbue_core.data_types import IssueCode
from vet.imbue_tools.types.vet_config import VetConfig
from vet.issue_identifiers.custom_guides import (
    load_custom_guides_from_directory,
    validate_custom_guides,
)
from vet.issue_identifiers.identification_guides import (
    ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE,
    build_merged_guides,
)


def test_get_custom_guides_directories_with_repo_path(tmp_path: Path) -> None:
    """Test that get_custom_guides_directories returns correct paths."""
    xdg_config = tmp_path / "xdg"
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()

    with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg_config)}):
        paths = get_custom_guides_directories(repo_path)

    assert len(paths) == 2
    assert paths[0] == repo_path / ".vet" / "custom_guides"
    assert paths[1] == xdg_config / "vet" / "custom_guides"


def test_get_custom_guides_directories_without_repo_path(tmp_path: Path) -> None:
    """Test directory discovery without repo path (only global)."""
    xdg_config = tmp_path / "xdg"

    with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg_config)}):
        paths = get_custom_guides_directories(repo_path=None)

    assert len(paths) == 1
    assert paths[0] == xdg_config / "vet" / "custom_guides"


def test_get_custom_guides_directories_finds_git_root(tmp_path: Path) -> None:
    """Test that it finds git root even when given subdirectory."""
    xdg_config = tmp_path / "xdg"
    git_root = tmp_path / "repo"
    git_root.mkdir()
    (git_root / ".git").mkdir()
    subdir = git_root / "src" / "deep" / "nested"
    subdir.mkdir(parents=True)

    with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg_config)}):
        paths = get_custom_guides_directories(subdir)

    # Should use git root, not subdir
    assert paths[0] == git_root / ".vet" / "custom_guides"


def test_end_to_end_local_custom_guides_only(tmp_path: Path) -> None:
    """Test end-to-end flow with only local custom guides."""
    xdg_config = tmp_path / "xdg"
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()

    # Create local custom guides
    local_guides_dir = repo_path / ".vet" / "custom_guides"
    local_guides_dir.mkdir(parents=True)
    (local_guides_dir / "logic_error.md").write_text(
        """# vet_custom_guideline_prefix
LOCAL: Check for edge cases
"""
    )

    # Load guides
    with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg_config)}):
        directories = list(reversed(get_custom_guides_directories(repo_path)))
        custom_overrides = {}
        for guides_dir in directories:
            dir_overrides = load_custom_guides_from_directory(guides_dir)
            custom_overrides.update(dir_overrides)

    # Validate and merge
    validate_custom_guides(custom_overrides)
    merged_guides = build_merged_guides(custom_overrides)

    # Verify
    assert len(custom_overrides) == 1
    assert IssueCode.LOGIC_ERROR in custom_overrides
    assert merged_guides[IssueCode.LOGIC_ERROR].guide.startswith("LOCAL: Check for edge cases\n\n")


def test_end_to_end_global_custom_guides_only(tmp_path: Path) -> None:
    """Test end-to-end flow with only global custom guides."""
    xdg_config = tmp_path / "xdg"
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    # Create global custom guides
    global_guides_dir = xdg_config / "vet" / "custom_guides"
    global_guides_dir.mkdir(parents=True)
    (global_guides_dir / "insecure_code.md").write_text(
        """# vet_custom_guideline_suffix
GLOBAL: Always check OWASP Top 10
"""
    )

    # Load guides
    with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg_config)}):
        directories = list(reversed(get_custom_guides_directories(repo_path)))
        custom_overrides = {}
        for guides_dir in directories:
            dir_overrides = load_custom_guides_from_directory(guides_dir)
            custom_overrides.update(dir_overrides)

    # Validate and merge
    validate_custom_guides(custom_overrides)
    merged_guides = build_merged_guides(custom_overrides)

    # Verify
    assert len(custom_overrides) == 1
    assert IssueCode.INSECURE_CODE in custom_overrides
    assert merged_guides[IssueCode.INSECURE_CODE].guide.endswith("\n\nGLOBAL: Always check OWASP Top 10")


def test_end_to_end_local_overrides_global(tmp_path: Path) -> None:
    """Test that local custom guides override global ones for the same issue code."""
    xdg_config = tmp_path / "xdg"
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()

    # Create global guide
    global_guides_dir = xdg_config / "vet" / "custom_guides"
    global_guides_dir.mkdir(parents=True)
    (global_guides_dir / "logic_error.md").write_text(
        """# vet_custom_guideline_prefix
GLOBAL PREFIX
"""
    )

    # Create local guide (same issue code)
    local_guides_dir = repo_path / ".vet" / "custom_guides"
    local_guides_dir.mkdir(parents=True)
    (local_guides_dir / "logic_error.md").write_text(
        """# vet_custom_guideline_prefix
LOCAL PREFIX (should win)
"""
    )

    # Load guides (global first, then local overrides)
    with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg_config)}):
        directories = list(reversed(get_custom_guides_directories(repo_path)))
        custom_overrides = {}
        for guides_dir in directories:
            dir_overrides = load_custom_guides_from_directory(guides_dir)
            custom_overrides.update(dir_overrides)  # Later overrides earlier

    # Validate and merge
    merged_guides = build_merged_guides(custom_overrides)

    # Verify local won
    assert custom_overrides[IssueCode.LOGIC_ERROR].prefix == "LOCAL PREFIX (should win)"
    assert merged_guides[IssueCode.LOGIC_ERROR].guide.startswith("LOCAL PREFIX (should win)\n\n")


def test_end_to_end_global_and_local_different_issue_codes(tmp_path: Path) -> None:
    """Test that global and local guides for different issue codes are both included."""
    xdg_config = tmp_path / "xdg"
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()

    # Create global guide for one issue
    global_guides_dir = xdg_config / "vet" / "custom_guides"
    global_guides_dir.mkdir(parents=True)
    (global_guides_dir / "logic_error.md").write_text(
        """# vet_custom_guideline_prefix
GLOBAL LOGIC
"""
    )

    # Create local guide for different issue
    local_guides_dir = repo_path / ".vet" / "custom_guides"
    local_guides_dir.mkdir(parents=True)
    (local_guides_dir / "insecure_code.md").write_text(
        """# vet_custom_guideline_prefix
LOCAL SECURITY
"""
    )

    # Load guides
    with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg_config)}):
        directories = list(reversed(get_custom_guides_directories(repo_path)))
        custom_overrides = {}
        for guides_dir in directories:
            dir_overrides = load_custom_guides_from_directory(guides_dir)
            custom_overrides.update(dir_overrides)

    # Validate and merge
    merged_guides = build_merged_guides(custom_overrides)

    # Verify both are present
    assert len(custom_overrides) == 2
    assert IssueCode.LOGIC_ERROR in custom_overrides
    assert IssueCode.INSECURE_CODE in custom_overrides
    assert merged_guides[IssueCode.LOGIC_ERROR].guide.startswith("GLOBAL LOGIC\n\n")
    assert merged_guides[IssueCode.INSECURE_CODE].guide.startswith("LOCAL SECURITY\n\n")


def test_end_to_end_no_custom_guides_uses_defaults(tmp_path: Path) -> None:
    """Test that when no custom guides exist, defaults are used."""
    xdg_config = tmp_path / "xdg"
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    # Don't create any custom guide directories

    # Load guides
    with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg_config)}):
        directories = list(reversed(get_custom_guides_directories(repo_path)))
        custom_overrides = {}
        for guides_dir in directories:
            dir_overrides = load_custom_guides_from_directory(guides_dir)
            custom_overrides.update(dir_overrides)

    # Verify no overrides
    assert len(custom_overrides) == 0

    # Build merged guides (should be all defaults)
    merged_guides = build_merged_guides(custom_overrides)

    # Should have all default guides
    assert len(merged_guides) == len(ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE)
    for code, guide in merged_guides.items():
        assert guide == ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE[code]


def test_vet_config_guides_by_code_property_with_custom_guides(tmp_path: Path) -> None:
    """Test VetConfig.guides_by_code property returns merged guides when set."""
    config = VetConfig()

    # Initially should return defaults
    assert config.guides_by_code == ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE

    # Set merged guides with custom override
    custom_overrides = {IssueCode.LOGIC_ERROR: load_custom_guides_from_directory(tmp_path).get(IssueCode.LOGIC_ERROR)}
    # Since tmp_path is empty, let's manually create one
    from vet.issue_identifiers.custom_guides import CustomGuideOverride

    custom_overrides = {
        IssueCode.LOGIC_ERROR: CustomGuideOverride(
            issue_code=IssueCode.LOGIC_ERROR,
            prefix="Custom",
            source_file=tmp_path / "test.md",
        )
    }
    merged_guides = build_merged_guides(custom_overrides)
    config.set_merged_guides(merged_guides)

    # Now should return merged guides
    assert config.guides_by_code == merged_guides
    assert config.guides_by_code[IssueCode.LOGIC_ERROR].guide.startswith("Custom\n\n")


def test_vet_config_guides_by_code_property_without_custom_guides() -> None:
    """Test VetConfig.guides_by_code property returns defaults when no custom guides."""
    config = VetConfig()

    # Should return defaults
    assert config.guides_by_code == ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE


def test_end_to_end_mixed_prefix_suffix_replace_modes(tmp_path: Path) -> None:
    """Test end-to-end with different modes for different issue codes."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    # Create guides with different modes
    guides_dir = repo_path / ".vet" / "custom_guides"
    guides_dir.mkdir(parents=True)

    (guides_dir / "logic_error.md").write_text(
        """# vet_custom_guideline_prefix
PREFIX MODE
"""
    )

    (guides_dir / "insecure_code.md").write_text(
        """# vet_custom_guideline_suffix
SUFFIX MODE
"""
    )

    (guides_dir / "test_coverage.md").write_text(
        """# vet_custom_guideline_replace
REPLACE MODE
"""
    )

    (guides_dir / "incomplete_integration_with_existing_code.md").write_text(
        """# vet_custom_guideline_prefix
PREFIX PART

# vet_custom_guideline_suffix
SUFFIX PART
"""
    )

    # Load and merge
    custom_overrides = load_custom_guides_from_directory(guides_dir)
    merged_guides = build_merged_guides(custom_overrides)

    # Verify each mode worked correctly
    assert merged_guides[IssueCode.LOGIC_ERROR].guide.startswith("PREFIX MODE\n\n")
    assert "PREFIX MODE" in merged_guides[IssueCode.LOGIC_ERROR].guide
    assert (
        ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE[IssueCode.LOGIC_ERROR].guide
        in merged_guides[IssueCode.LOGIC_ERROR].guide
    )

    assert merged_guides[IssueCode.INSECURE_CODE].guide.endswith("\n\nSUFFIX MODE")
    assert (
        ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE[IssueCode.INSECURE_CODE].guide
        in merged_guides[IssueCode.INSECURE_CODE].guide
    )

    assert merged_guides[IssueCode.TEST_COVERAGE].guide == "REPLACE MODE"
    assert (
        ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE[IssueCode.TEST_COVERAGE].guide
        not in merged_guides[IssueCode.TEST_COVERAGE].guide
    )

    assert "PREFIX PART" in merged_guides[IssueCode.INCOMPLETE_INTEGRATION_WITH_EXISTING_CODE].guide
    assert "SUFFIX PART" in merged_guides[IssueCode.INCOMPLETE_INTEGRATION_WITH_EXISTING_CODE].guide
    assert (
        ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE[IssueCode.INCOMPLETE_INTEGRATION_WITH_EXISTING_CODE].guide
        in merged_guides[IssueCode.INCOMPLETE_INTEGRATION_WITH_EXISTING_CODE].guide
    )


def test_end_to_end_with_invalid_and_valid_files(tmp_path: Path) -> None:
    """Test that invalid files are skipped and valid ones are processed."""
    guides_dir = tmp_path / "guides"
    guides_dir.mkdir()

    # Valid file
    (guides_dir / "logic_error.md").write_text(
        """# vet_custom_guideline_prefix
VALID
"""
    )

    # Invalid issue code
    (guides_dir / "not_a_real_issue.md").write_text(
        """# vet_custom_guideline_prefix
INVALID
"""
    )

    # Empty file
    (guides_dir / "insecure_code.md").write_text("")

    # Non-markdown file (should be ignored)
    (guides_dir / "readme.txt").write_text("Not a guide")

    # Another valid file
    (guides_dir / "test_coverage.md").write_text(
        """# vet_custom_guideline_suffix
ALSO VALID
"""
    )

    # Load guides
    custom_overrides = load_custom_guides_from_directory(guides_dir)

    # Should only have the two valid guides
    assert len(custom_overrides) == 2
    assert IssueCode.LOGIC_ERROR in custom_overrides
    assert IssueCode.TEST_COVERAGE in custom_overrides
    assert custom_overrides[IssueCode.LOGIC_ERROR].prefix == "VALID"
    assert custom_overrides[IssueCode.TEST_COVERAGE].suffix == "ALSO VALID"


def test_end_to_end_preserves_examples_and_exceptions(tmp_path: Path) -> None:
    """Test that examples and exceptions from default guides are preserved after merge."""
    guides_dir = tmp_path / "guides"
    guides_dir.mkdir()

    # Pick a guide that has examples and exceptions
    (guides_dir / "commit_message_mismatch.md").write_text(
        """# vet_custom_guideline_prefix
Custom prefix for commit message checks
"""
    )

    # Load and merge
    custom_overrides = load_custom_guides_from_directory(guides_dir)
    merged_guides = build_merged_guides(custom_overrides)

    # Get the merged guide
    merged = merged_guides[IssueCode.COMMIT_MESSAGE_MISMATCH]
    original = ISSUE_IDENTIFICATION_GUIDES_BY_ISSUE_CODE[IssueCode.COMMIT_MESSAGE_MISMATCH]

    # Verify guide text changed
    assert merged.guide != original.guide
    assert merged.guide.startswith("Custom prefix for commit message checks\n\n")

    # Verify examples and exceptions preserved
    assert merged.examples == original.examples
    assert merged.exceptions == original.exceptions
    assert merged.additional_guide_for_agent == original.additional_guide_for_agent
