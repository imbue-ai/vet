from datetime import datetime
from datetime import timezone

from imbue_tools.repo_utils.context_prefix import SubrepoContext
from imbue_tools.types.imbue_verify_config import ImbueVerifyConfig
from imbue_verify.telemetry import create_imbue_verify_issues_found_event


async def test_create_imbue_verify_issues_found_event_with_created_at() -> None:
    now = datetime.now(timezone.utc)  # noqa: F821
    event = await create_imbue_verify_issues_found_event(
        config=ImbueVerifyConfig(),
        base_commit="",
        diff="",
        goal="",
        subrepo_context=SubrepoContext(
            subrepo_context_strategy_label="",
            repo_context_files=tuple(),
        ),
        created_at=now,
    )
    assert event.created_at == now


async def test_without_created_at() -> None:
    event = await create_imbue_verify_issues_found_event(
        config=ImbueVerifyConfig(),
        base_commit="",
        diff="",
        goal="",
        subrepo_context=SubrepoContext(
            subrepo_context_strategy_label="",
            repo_context_files=tuple(),
        ),
    )
    assert isinstance(event.created_at, datetime)
