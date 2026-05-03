from __future__ import annotations

import asyncio

from core.contracts.types import JobRecord


class JobTerminalWaiter:
    """Bridges background workers to chat handlers waiting on a terminal job status."""

    def __init__(self, *, max_terminal_remembered: int = 2000) -> None:
        self._futures: dict[str, asyncio.Future[JobRecord]] = {}
        self._terminal: dict[str, JobRecord] = {}
        self._lock = asyncio.Lock()
        self._max_terminal = max_terminal_remembered

    def _trim_terminal(self) -> None:
        while len(self._terminal) > self._max_terminal:
            first = next(iter(self._terminal))
            self._terminal.pop(first, None)

    async def subscribe(
        self,
        job_id: str,
        *,
        snapshot: JobRecord | None = None,
    ) -> asyncio.Future[JobRecord]:
        loop = asyncio.get_running_loop()
        if snapshot is not None and snapshot["status"] in (
            "succeeded",
            "failed",
            "canceled",
        ):
            fut: asyncio.Future[JobRecord] = loop.create_future()
            fut.set_result(dict(snapshot))
            return fut
        async with self._lock:
            cached = self._terminal.get(job_id)
            if cached is not None:
                fut = loop.create_future()
                fut.set_result(dict(cached))
                return fut
            fut = self._futures.get(job_id)
            if fut is None:
                fut = loop.create_future()
                self._futures[job_id] = fut
            return fut

    async def publish_terminal(self, record: JobRecord) -> None:
        if record["status"] not in ("succeeded", "failed", "canceled"):
            return
        snap = dict(record)
        async with self._lock:
            self._terminal[record["job_id"]] = snap
            self._trim_terminal()
            fut = self._futures.pop(record["job_id"], None)
        if fut is not None and not fut.done():
            fut.set_result(snap)
