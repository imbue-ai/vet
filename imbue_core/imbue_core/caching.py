from __future__ import annotations

import asyncio
import os
from functools import lru_cache
from pathlib import Path
from types import TracebackType
from typing import Generic
from typing import Self
from typing import Sequence
from typing import TypeVar

from diskcache import Cache
from diskcache import JSONDisk

from imbue_core.cattrs_serialization import deserialize_from_json
from imbue_core.cattrs_serialization import serialize_to_json
from imbue_core.frozen_utils import FrozenDict
from imbue_core.frozen_utils import FrozenMapping

ValueType = TypeVar("ValueType", covariant=True)


class AsyncCacheInterface(Generic[ValueType]):
    async def __aenter__(self) -> Self:
        raise NotImplementedError()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        raise NotImplementedError()

    async def set(
        self,
        key: str,
        # pyre-fixme[46]: ValueType is covariant
        value: ValueType,
        expire: int | None = None,
        read: bool = False,
        tag: str | None = None,
        retry: bool = False,
    ) -> bool:
        raise NotImplementedError()

    async def get(
        self,
        key: str,
        default: ValueType | None = None,
        read: bool = False,
        expire_time: bool = False,
        tag: bool = False,
        retry: bool = False,
    ) -> ValueType | None:
        raise NotImplementedError()

    async def get_all(
        self,
        keys: Sequence[str],
        default: ValueType | None = None,
        read: bool = False,
        expire_time: bool = False,
        tag: bool = False,
        retry: bool = False,
    ) -> FrozenMapping[str, ValueType | None]:
        raise NotImplementedError()

    async def get_all_keys(self, reverse: bool = False) -> tuple[str, ...]:
        raise NotImplementedError()


class AsyncCache(AsyncCacheInterface[ValueType], Generic[ValueType]):
    def __init__(self, path: Path, value_cls: type[ValueType]) -> None:
        self.path = path
        self.value_cls = value_cls
        self.cache: Cache | None = None

    async def _build_cache(self) -> Cache:
        loop = asyncio.get_running_loop()
        # pyre-ignore[6]: pyre doesn't like the lru cache here
        return await loop.run_in_executor(None, get_cache, self.path)

    async def __aenter__(self) -> Self:
        loop = asyncio.get_running_loop()
        cache = await self._build_cache()
        self.cache = cache
        await loop.run_in_executor(None, cache.__enter__)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        loop = asyncio.get_running_loop()
        cache = self.cache
        assert cache is not None
        result = await loop.run_in_executor(
            None, cache.__exit__, exc_type, exc_val, exc_tb
        )
        self.cache = None
        return result

    async def set(
        self,
        key: str,
        # pyre-fixme[46]: ValueType is covariant
        value: ValueType,
        expire: int | None = None,
        read: bool = False,
        tag: str | None = None,
        retry: bool = False,
    ) -> bool:
        cache = self.cache
        assert cache is not None
        loop = asyncio.get_running_loop()
        assert isinstance(
            value, self.value_cls
        ), f"Expected {self.value_cls}, got {type(value)}"
        serialized_value = serialize_to_json(value)
        return await loop.run_in_executor(
            None, cache.set, key, serialized_value, expire, read, tag, retry
        )

    async def delete(self, key: str, retry: bool = False) -> bool:
        cache = self.cache
        assert cache is not None
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, cache.delete, key, retry)

    async def get(
        self,
        key: str,
        default: ValueType | None = None,
        read: bool = False,
        expire_time: bool = False,
        tag: bool = False,
        retry: bool = False,
    ) -> ValueType | None:
        cache = self.cache
        assert cache is not None
        loop = asyncio.get_running_loop()
        value = await loop.run_in_executor(
            None, cache.get, key, None, read, expire_time, tag, retry
        )
        if value is None:
            return default
        deserialized_value = deserialize_from_json(value)
        assert isinstance(
            deserialized_value, self.value_cls
        ), f"Expected {self.value_cls}, got {type(deserialized_value)}"
        return deserialized_value

    # TODO: this is not smart implementation, but at least it will be possible to optimize later without refactoring
    async def get_all(
        self,
        keys: Sequence[str],
        default: ValueType | None = None,
        read: bool = False,
        expire_time: bool = False,
        tag: bool = False,
        retry: bool = False,
    ) -> FrozenMapping[str, ValueType | None]:
        tasks = {}
        for key in keys:
            tasks[key] = self.get(key, default, read, expire_time, tag, retry)
        results = await asyncio.gather(*tasks.values())
        return FrozenDict(zip(tasks.keys(), results))

    # TODO: might be nice to get iterkeys back someday, but whatever for now, too annoying to get the sync/async right
    async def get_all_keys(self, reverse: bool = False) -> tuple[str, ...]:
        cache = self.cache
        assert cache is not None
        loop = asyncio.get_running_loop()
        return tuple(await loop.run_in_executor(None, cache.iterkeys, reverse))


@lru_cache
def get_cache(data_path: Path) -> Cache:
    # not sure if the size limit applies when eviction is none, but ~64GB should be enough for now
    return Cache(
        str(data_path),
        disk=JSONDisk,
        disk_compress_level=0,
        eviction_policy="none",
        size_limit=2**36,
    )


def get_default_llm_response_cache() -> Path:
    return Path(
        os.environ.get(
            "RESPONSE_CACHE_PATH", os.path.expanduser("~/.llm_response_cache")
        )
    )


def get_default_count_tokens_cache() -> Path:
    return Path(
        os.environ.get(
            "COUNT_TOKENS_CACHE_PATH", os.path.expanduser("~/.count_tokens_cache")
        )
    )


def get_test_llm_response_cache() -> Path:
    return Path(os.path.expanduser("~/.llm_test_response_cache"))


class InMemoryCache(AsyncCacheInterface[ValueType], Generic[ValueType]):
    def __init__(self, values: tuple[ValueType, ...]) -> None:
        self.values = values

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass

    async def get(
        self,
        key: str,
        default: ValueType | None = None,
        read: bool = False,
        expire_time: bool = False,
        tag: bool = False,
        retry: bool = False,
    ) -> ValueType | None:
        return self.values[int(key)]

    async def get_all(
        self,
        keys: Sequence[str],
        default: ValueType | None = None,
        read: bool = False,
        expire_time: bool = False,
        tag: bool = False,
        retry: bool = False,
    ) -> FrozenMapping[str, ValueType | None]:
        return FrozenDict(zip(await self.get_all_keys(), self.values))

    async def get_all_keys(self, reverse: bool = False) -> tuple[str, ...]:
        return tuple(map(str, range(len(self.values))))
