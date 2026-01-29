from pathlib import Path

from loguru import logger
from syrupy.assertion import SnapshotAssertion

from imbue_core.caching import AsyncCache
from imbue_core.cattrs_serialization import deserialize_from_json
from imbue_core.cattrs_serialization import serialize_to_json


async def preload_llm_cache(persistent_cache_path: Path, temp_cache: AsyncCache) -> None:
    logger.info(
        "Loading existing cache from {persistent_cache_path}",
        persistent_cache_path=persistent_cache_path,
    )
    assert persistent_cache_path.exists(), f"Cache file {persistent_cache_path} does not exist."
    existing_data = deserialize_from_json(persistent_cache_path.read_text())
    async with temp_cache as cache:
        for key, value in existing_data.items():
            await cache.set(key, value)


async def record_llm_responses_in_cache(temp_cache: AsyncCache, persistent_cache_path: Path) -> None:
    logger.info(
        "Updating cache (!!!) at {persistent_cache_path}",
        persistent_cache_path=persistent_cache_path,
    )
    async with temp_cache as cache:
        all_keys = await cache.get_all_keys()
        data = await cache.get_all(all_keys)
        if data:
            persistent_cache_path.parent.mkdir(parents=True, exist_ok=True)
            persistent_cache_path.write_text(serialize_to_json(data), encoding="utf-8")


def _sanitize_snapshot_name(snapshot_name: str) -> str:
    return snapshot_name.replace("/", "").replace("\\", "")


def get_cache_file_from_snapshot_core(snapshot: SnapshotAssertion, suffix: str) -> Path:
    # To prevent syrupy from cleaning the cache up immediately after written, we use this suffix and register it with pytest.
    # Make sure to add a line like `--snapshot-ignore-file-extensions={suffix}` to the project's pytest.ini

    # Goal here is a cache file per test, not per test-file.
    test_file = Path(snapshot.test_location.filepath)
    snapshot_dir = test_file.parent / "__snapshots__" / test_file.stem
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    cache_file = snapshot_dir / f"{_sanitize_snapshot_name(snapshot.test_location.testname)}.{suffix}"
    return cache_file


def get_cache_file_from_snapshot(snapshot: SnapshotAssertion) -> Path:
    return get_cache_file_from_snapshot_core(snapshot, "llm_cache_json")


def get_count_tokens_cache_file_from_snapshot(snapshot: SnapshotAssertion) -> Path:
    return get_cache_file_from_snapshot_core(snapshot, "count_tokens_cache_json")
