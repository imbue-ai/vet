from __future__ import annotations

import pytest

from vet.imbue_core.data_types import CustomGuideConfig
from vet.imbue_core.data_types import CustomGuidesConfig
from vet.imbue_core.data_types import IssueCode
from vet.issue_identifiers.identification_guides import IssueIdentificationGuide
from vet.issue_identifiers.identification_guides import apply_custom_guides


@pytest.fixture
def built_in_guides() -> dict[IssueCode, IssueIdentificationGuide]:
    return {
        IssueCode.LOGIC_ERROR: IssueIdentificationGuide(
            issue_code=IssueCode.LOGIC_ERROR,
            guide="- Built-in logic error guide",
            additional_guide_for_agent="agent guide",
            examples=("example1",),
            exceptions=("exception1",),
        ),
        IssueCode.INSECURE_CODE: IssueIdentificationGuide(
            issue_code=IssueCode.INSECURE_CODE,
            guide="- Built-in insecure code guide",
        ),
    }


def test_apply_none_config_returns_unchanged(
    built_in_guides: dict[IssueCode, IssueIdentificationGuide],
) -> None:
    result = apply_custom_guides(built_in_guides, None)
    assert result is built_in_guides


def test_apply_suffix(
    built_in_guides: dict[IssueCode, IssueIdentificationGuide],
) -> None:
    config = CustomGuidesConfig(guides={"logic_error": CustomGuideConfig(suffix="- Custom suffix")})
    result = apply_custom_guides(built_in_guides, config)
    assert result[IssueCode.LOGIC_ERROR].guide == "- Built-in logic error guide\n- Custom suffix"


def test_apply_prefix(
    built_in_guides: dict[IssueCode, IssueIdentificationGuide],
) -> None:
    config = CustomGuidesConfig(guides={"logic_error": CustomGuideConfig(prefix="- Custom prefix")})
    result = apply_custom_guides(built_in_guides, config)
    assert result[IssueCode.LOGIC_ERROR].guide == "- Custom prefix\n- Built-in logic error guide"


def test_apply_replace(
    built_in_guides: dict[IssueCode, IssueIdentificationGuide],
) -> None:
    config = CustomGuidesConfig(guides={"logic_error": CustomGuideConfig(replace="- Replacement guide")})
    result = apply_custom_guides(built_in_guides, config)
    assert result[IssueCode.LOGIC_ERROR].guide == "- Replacement guide"


def test_apply_prefix_and_suffix(
    built_in_guides: dict[IssueCode, IssueIdentificationGuide],
) -> None:
    config = CustomGuidesConfig(guides={"logic_error": CustomGuideConfig(prefix="- Before", suffix="- After")})
    result = apply_custom_guides(built_in_guides, config)
    assert result[IssueCode.LOGIC_ERROR].guide == "- Before\n- Built-in logic error guide\n- After"


def test_apply_preserves_non_guide_fields(
    built_in_guides: dict[IssueCode, IssueIdentificationGuide],
) -> None:
    config = CustomGuidesConfig(guides={"logic_error": CustomGuideConfig(replace="- Replacement")})
    result = apply_custom_guides(built_in_guides, config)
    guide = result[IssueCode.LOGIC_ERROR]
    assert guide.additional_guide_for_agent == "agent guide"
    assert guide.examples == ("example1",)
    assert guide.exceptions == ("exception1",)


def test_apply_does_not_modify_other_codes(
    built_in_guides: dict[IssueCode, IssueIdentificationGuide],
) -> None:
    config = CustomGuidesConfig(guides={"logic_error": CustomGuideConfig(suffix="- Custom suffix")})
    result = apply_custom_guides(built_in_guides, config)
    assert result[IssueCode.INSECURE_CODE].guide == "- Built-in insecure code guide"
