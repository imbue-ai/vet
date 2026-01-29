from pathlib import Path
from typing import Callable
from typing import Generator

import pytest
from pytest_asyncio import fixture as async_fixture
from syrupy.assertion import SnapshotAssertion

from imbue_core.agents.configs import LanguageModelGenerationConfig
from imbue_core.agents.llm_apis.anthropic_api import AnthropicModelName
from imbue_core.async_monkey_patches_test import explode_on_error  # noqa: F401
from imbue_core.test_repo_utils import make_simple_test_git_repo
from imbue_core.test_utils import make_llm_cache_with_snapshot

llm_cache_path = async_fixture(make_llm_cache_with_snapshot)


# this is copied from sculptor/conftest.py
# (it must be copied rather than imported because of the autouse)
@pytest.fixture(autouse=True)
def always_explode_on_error(
    explode_on_error: Callable[[], Generator[None, None, None]],
) -> Generator[None, None, None]:
    """
    Ensures that we do not log errors or exceptions during testing.

    If your test is checking error handling behavior (and you expect to see a log_exception call),
    use the `expect_exact_logged_errors` decorator to suppress the logging of those errors.
    """
    yield


def llm_config_for_test(
    llm_cache_path: Path, snapshot: SnapshotAssertion, is_caching_inputs: bool = False
) -> LanguageModelGenerationConfig:
    return LanguageModelGenerationConfig(
        model_name=AnthropicModelName.CLAUDE_4_SONNET_2025_05_14,
        cache_path=llm_cache_path,
        is_running_offline=not snapshot.session.update_snapshots,
        is_caching_inputs=is_caching_inputs,
    )


simple_test_git_repo = pytest.fixture(make_simple_test_git_repo)
