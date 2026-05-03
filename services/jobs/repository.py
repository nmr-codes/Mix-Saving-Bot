from __future__ import annotations

import asyncio
from collections.abc import Iterable

from core.contracts.types import JobRecord


class InMemoryJobRepository:
    """Thread-safe asyncio job persistence (development / single-worker)."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._by_id: dict[str, JobRecord] = {}

    async def save(self, record: JobRecord) -> None:
        async with self._lock:
            self._by_id[record["job_id"]] = record

    async def get(self, job_id: str) -> JobRecord | None:
        async with self._lock:
            row = self._by_id.get(job_id)
            return dict(row) if row else None

    async def find_active_by_dedupe(self, dedupe_key: str) -> JobRecord | None:
        async with self._lock:
            for r in self._by_id.values():
                if r.get("dedupe_key") != dedupe_key:
                    continue
                if r["status"] in ("queued", "running"):
                    return dict(r)
            return None

    async def list_active_for_chat(self, chat_id: int, limit: int) -> list[JobRecord]:
        out: list[JobRecord] = []
        async with self._lock:
            for r in self._by_id.values():
                if r["request"]["chat"]["chat_id"] != chat_id:
                    continue
                if r["status"] in ("queued", "running"):
                    out.append(dict(r))
        out.sort(key=lambda x: x["created_at_unix"], reverse=True)
        return out[:limit]

    def all_ids(self) -> Iterable[str]:
        return self._by_id.keys()
