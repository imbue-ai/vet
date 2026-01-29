import contextlib
import shutil
import tempfile
import time
from pathlib import Path
from typing import AsyncGenerator
from typing import Callable
from typing import Generator

from loguru import logger
from syrupy.assertion import SnapshotAssertion

from imbue_core.agents.llm_apis.data_types import CachedCostedLanguageModelResponse
from imbue_core.agents.llm_apis.data_types import CachedCostedModelResponse
from imbue_core.agents.llm_apis.data_types import CachedCountTokensResponse
from imbue_core.agents.llm_apis.llm_testing_utils import check_llm_responses_in_cache
from imbue_core.caching import AsyncCache
from imbue_core.llm_testing_utils import get_cache_file_from_snapshot
from imbue_core.llm_testing_utils import get_count_tokens_cache_file_from_snapshot
from imbue_core.llm_testing_utils import preload_llm_cache
from imbue_core.llm_testing_utils import record_llm_responses_in_cache


def info_if_not_quiet(quiet: bool, message: str) -> None:
    if not quiet:
        logger.info(message)


@contextlib.contextmanager
def create_temp_dir(root_dir: Path) -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory(dir=root_dir) as temp_dir:
        yield Path(temp_dir)
        shutil.rmtree(temp_dir)


def wait_until(
    condition: Callable[[], bool], timeout: float = 5.0, interval: float = 0.5
) -> None:
    start_time = time.monotonic()
    while True:
        if condition():
            return
        if time.monotonic() - start_time > timeout:
            raise TimeoutError("Condition not met within timeout period")
        time.sleep(interval)


async def make_llm_cache_with_snapshot_core(
    snapshot: SnapshotAssertion,
    json_cache_file: Path,
    value_cls: type[CachedCostedModelResponse],
    quiet: bool = True,
    suffix: str = "",
) -> AsyncGenerator[Path, None]:
    info_if_not_quiet(quiet, f"Using llm_cache_pathfixture: {json_cache_file=}")

    with tempfile.TemporaryDirectory() as cache_path_string:
        cache_path = Path(cache_path_string)
        cache_context = AsyncCache(cache_path, value_cls)

        if not snapshot.session.update_snapshots:
            if json_cache_file.exists():
                await preload_llm_cache(json_cache_file, cache_context)

        yield cache_path
        info_if_not_quiet(
            quiet, "Finished with llm_cache_pathfixture, updating cache if needed."
        )

        if snapshot.session.update_snapshots:
            await record_llm_responses_in_cache(cache_context, json_cache_file)

        await check_llm_responses_in_cache(snapshot, cache_context, suffix)
        info_if_not_quiet(quiet, "Finished with llm_cache_pathfixture, checking cache.")


async def make_llm_cache_with_snapshot(
    snapshot: SnapshotAssertion, quiet: bool = True
) -> AsyncGenerator[Path, None]:
    json_cache_file = get_cache_file_from_snapshot(snapshot)
    async for path in make_llm_cache_with_snapshot_core(
        snapshot, json_cache_file, CachedCostedLanguageModelResponse, quiet
    ):
        yield path


async def make_count_tokens_cache_with_snapshot(
    snapshot: SnapshotAssertion, quiet: bool = True
) -> AsyncGenerator[Path, None]:
    json_cache_file = get_count_tokens_cache_file_from_snapshot(snapshot)
    async for path in make_llm_cache_with_snapshot_core(
        snapshot, json_cache_file, CachedCountTokensResponse, quiet, "_count_tokens"
    ):
        yield path
