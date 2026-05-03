from __future__ import annotations

from typing import Protocol

from core.contracts.types import CacheEntryDict


class CacheStore(Protocol):
    async def get(self, cache_key: str) -> CacheEntryDict | None:
        ...

    async def put_from_path(self, cache_key: str, src_path: str) -> CacheEntryDict:
        ...

    async def delete(self, cache_key: str) -> None:
        ...

    async def touch_ttl(self, cache_key: str) -> None:
        ...
