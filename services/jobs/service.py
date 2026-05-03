from __future__ import annotations

import time

from core.contracts.types import JobOutputRef, JobRecord, SubmitDownloadRequest

from services.jobs.model import make_job_record, new_job_id
from services.jobs.repository import InMemoryJobRepository
from services.jobs.terminal_waiter import JobTerminalWaiter


class JobServiceImpl:
    def __init__(
        self,
        repo: InMemoryJobRepository,
        *,
        waiter: JobTerminalWaiter | None = None,
    ) -> None:
        self._repo = repo
        self._waiter = waiter

    async def submit(
        self,
        req: SubmitDownloadRequest,
        *,
        dedupe_key: str | None = None,
    ) -> tuple[JobRecord, bool]:
        if dedupe_key:
            active = await self._repo.find_active_by_dedupe(dedupe_key)
            if active is not None:
                return active, False
        job_id = new_job_id()
        rec = make_job_record(job_id, "queued", req, dedupe_key=dedupe_key)
        await self._repo.save(rec)
        return rec, True

    async def get(self, job_id: str) -> JobRecord | None:
        return await self._repo.get(job_id)

    async def mark_running(self, job_id: str) -> None:
        rec = await self._repo.get(job_id)
        if rec is None:
            return
        rec["status"] = "running"
        rec["updated_at_unix"] = time.time()
        await self._repo.save(rec)

    async def mark_succeeded(self, job_id: str, outputs: list[JobOutputRef]) -> None:
        rec = await self._repo.get(job_id)
        if rec is None:
            return
        rec["status"] = "succeeded"
        rec["outputs"] = outputs
        rec["updated_at_unix"] = time.time()
        await self._repo.save(rec)
        if self._waiter:
            await self._waiter.publish_terminal(dict(rec))

    async def mark_failed(self, job_id: str, code: str, safe_message: str) -> None:
        rec = await self._repo.get(job_id)
        if rec is None:
            return
        rec["status"] = "failed"
        rec["error_code"] = code
        rec["error_message_safe"] = safe_message
        rec["updated_at_unix"] = time.time()
        await self._repo.save(rec)
        if self._waiter:
            await self._waiter.publish_terminal(dict(rec))

    async def mark_canceled(self, job_id: str) -> None:
        rec = await self._repo.get(job_id)
        if rec is None:
            return
        rec["status"] = "canceled"
        rec["updated_at_unix"] = time.time()
        await self._repo.save(rec)
        if self._waiter:
            await self._waiter.publish_terminal(dict(rec))

    async def list_active_for_chat(self, chat_id: int, limit: int) -> list[JobRecord]:
        return await self._repo.list_active_for_chat(chat_id, limit)
