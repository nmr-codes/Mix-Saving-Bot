from __future__ import annotations

import asyncio
from typing import Any

from services.dedupe_cache import DownloadCache
from services.logging_config import get_logger
from services.queue_manager import JobQueueManager, QueueOverflowError
from services.types import Job, JobStatus, TaskResult

log = get_logger("services.pipeline")


class TaskPipeline:
    """
    Bot-facing entry: reserve dedupe keys, enqueue downloader jobs, await results.

    Reservations use :meth:`DownloadCache.try_reserve` so concurrent duplicate
    requests do not enter the queue. The Downloader agent must pair this with
    :meth:`DownloadCache.commit` / :meth:`DownloadCache.abort` inside the job
    processor (see :func:`services.remote_backend.build_download_processor`).
    """

    def __init__(
        self,
        *,
        queue: JobQueueManager,
        cache: DownloadCache | None = None,
    ) -> None:
        self._queue = queue
        self._cache = cache

    async def submit_download(
        self,
        *,
        url: str,
        media: str,
        timeout: float | None = None,
    ) -> TaskResult:
        job = Job(
            kind="download",
            payload={"url": url, "media": media},
            retry_on_failure=False,
        )
        payload: dict[str, Any] = job.payload
        key: str | None = None

        if self._cache is not None:
            key = self._cache.dedupe_key_for_payload(payload)
            if await self._cache.try_reserve(key, job.id) == "duplicate":
                return TaskResult(
                    job_id=job.id,
                    status=JobStatus.REJECTED_DUPLICATE,
                    message="This resource was already fetched recently.",
                    detail={"dedupe_key": key, "error_code": "DUPLICATE"},
                )

        try:
            return await self._queue.enqueue_and_wait(job, timeout=timeout)
        except asyncio.TimeoutError:
            log.warning(
                "enqueue_and_wait timed out; dedupe reservation still held for job",
                extra={"job_id": job.id, "dedupe_key": key},
            )
            raise
        except QueueOverflowError:
            if self._cache is not None and key is not None:
                await self._cache.abort(key)
            raise
