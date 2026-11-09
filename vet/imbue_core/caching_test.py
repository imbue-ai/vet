import asyncio
import json
import zlib
from pathlib import Path
from typing import Any

from diskcache_community import Cache
from diskcache_community import Disk
from diskcache_community import JSONDisk

from vet.imbue_core.agents.llm_apis.data_types import CachedCountTokensResponse
from vet.imbue_core.agents.llm_apis.data_types import CountTokensResponse
from vet.imbue_core.caching import AsyncCache
from vet.imbue_core.cattrs_serialization import serialize_to_json

_planted_calls: list[str] = []


def _planted() -> bytes:
    _planted_calls.append("ran")
    fake = CachedCountTokensResponse(response=CountTokensResponse(input_tokens=9999))
    return zlib.compress(json.dumps(serialize_to_json(fake)).encode())


class _Planted:
    def __reduce__(self) -> tuple:
        return (_planted, ())


class _PickleWritingDisk(JSONDisk):
    def store(self, *args: Any, **kwargs: Any) -> Any:
        return Disk.store(self, *args, **kwargs)


def test_pickled_entry_is_a_miss_and_is_not_unpickled(tmp_path: Path) -> None:
    value = CachedCountTokensResponse(response=CountTokensResponse(input_tokens=7))

    async def store() -> None:
        async with AsyncCache(tmp_path, CachedCountTokensResponse) as cache:
            await cache.set("key", value)
            assert await cache.get("key") == value

    async def load() -> CachedCountTokensResponse | None:
        async with AsyncCache(tmp_path, CachedCountTokensResponse) as cache:
            return await cache.get("key")

    asyncio.run(store())

    with Cache(str(tmp_path), disk=_PickleWritingDisk) as other_writer:
        other_writer.set("key", _Planted())

    assert asyncio.run(load()) is None
    assert _planted_calls == []
