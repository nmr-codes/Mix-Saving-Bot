from __future__ import annotations

import asyncio
import contextlib

import pytest

from services.queue_manager import JobQueueManager
from services.types import Job, JobStatus, TaskResult
from services.worker import Worker


@pytest.mark.asyncio
async def test_worker_completed_job_acknowledged() -> None:
    async def processor(job: Job) -> TaskResult:
        return TaskResult(job_id=job.id, status=JobStatus.COMPLETED)

    q = JobQueueManager(maxsize=4)
    w = Worker(q, processors={"download": processor}, name="t0")
    loop_task = asyncio.create_task(w.run())
    res = await q.enqueue_and_wait(Job(kind="download", payload={}), timeout=2.0)
    assert res.status == JobStatus.COMPLETED
    loop_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await loop_task


@pytest.mark.asyncio
async def test_worker_missing_processor_fails_job() -> None:
    async def noop(_j: Job) -> TaskResult:
        raise AssertionError("unreachable")

    q = JobQueueManager(maxsize=4)
    w = Worker(q, processors={"download": noop}, name="t1")
    loop_task = asyncio.create_task(w.run())
    res = await q.enqueue_and_wait(
        Job(kind="missing", payload={}, retry_on_failure=False),
        timeout=2.0,
    )
    assert res.status == JobStatus.FAILED
    assert res.detail.get("error_code") == "NO_PROCESSOR"
    loop_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await loop_task
