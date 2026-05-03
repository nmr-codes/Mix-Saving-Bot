"""
Runnable smoke test: queue + worker pool + cache + pipeline (mock download).

Run from repo root:  python -m services
"""

from __future__ import annotations

import asyncio

from services.dedupe_cache import DownloadCache
from services.logging_config import setup_json_logging
from services.pipeline import TaskPipeline
from services.queue_manager import JobQueueManager
from services.types import Job, JobStatus, TaskResult
from services.worker import WorkerPool


async def _mock_download(job: Job) -> TaskResult:
    await asyncio.sleep(0.01)
    return TaskResult(
        job_id=job.id,
        status=JobStatus.COMPLETED,
        message="mock_ok",
        detail={"url": job.payload.get("url")},
    )


async def _main() -> None:
    setup_json_logging()
    q = JobQueueManager(maxsize=8, stale_after_seconds=30.0)
    cache = DownloadCache()
    pipe = TaskPipeline(queue=q, cache=cache)

    async def processor(job: Job) -> TaskResult:
        result = await _mock_download(job)
        key = cache.dedupe_key_for_payload(job.payload)
        if result.status == JobStatus.COMPLETED:
            await cache.commit(key)
        else:
            await cache.abort(key)
        return result

    pool = WorkerPool(q, processors={"download": processor}, workers=2)
    await pool.start()

    r1 = await pipe.submit_download(url="https://example.com/mix", media="audio")
    r2 = await pipe.submit_download(url="https://example.com/mix", media="audio")
    assert r1.status == JobStatus.COMPLETED
    assert r2.status == JobStatus.REJECTED_DUPLICATE

    await pool.stop()


if __name__ == "__main__":
    asyncio.run(_main())
