from __future__ import annotations

import asyncio

import pytest

from services.queue_manager import JobQueueManager, QueueClosedError, QueueOverflowError
from services.types import Job, JobStatus, TaskResult


@pytest.mark.asyncio
async def test_enqueue_dequeue_ack_roundtrip() -> None:
    q = JobQueueManager(maxsize=4)
    job = Job(kind="download", payload={})
    await q.enqueue(job)
    got = await q.dequeue()
    assert got.id == job.id
    q.publish_result(
        TaskResult(job_id=job.id, status=JobStatus.COMPLETED, message="ok"),
    )
    q.acknowledge(got)


@pytest.mark.asyncio
async def test_enqueue_and_wait_receives_result() -> None:
    q = JobQueueManager()
    job = Job(kind="download", payload={})

    async def publisher() -> None:
        j = await q.dequeue()
        q.publish_result(TaskResult(job_id=j.id, status=JobStatus.COMPLETED))

    t = asyncio.create_task(publisher())
    res = await q.enqueue_and_wait(job, timeout=2.0)
    await t
    assert res.job_id == job.id
    assert res.status == JobStatus.COMPLETED


@pytest.mark.asyncio
async def test_enqueue_overflow() -> None:
    q = JobQueueManager(maxsize=1)
    await q.enqueue(Job(payload={}))
    with pytest.raises(QueueOverflowError):
        await q.enqueue(Job(payload={}))


@pytest.mark.asyncio
async def test_closed_rejects_enqueue() -> None:
    q = JobQueueManager(maxsize=10)
    q.close()
    with pytest.raises(QueueClosedError):
        await q.enqueue(Job(payload={}))


@pytest.mark.asyncio
async def test_nack_returns_job_to_queue() -> None:
    q = JobQueueManager(maxsize=4)
    job = Job(max_attempts=5, retry_on_failure=True)
    await q.enqueue(job)
    dq = await q.dequeue()
    assert q.pending_qsize() == 0
    assert q.nack(dq) is True
    assert q.pending_qsize() == 1


@pytest.mark.asyncio
async def test_nack_exhausted_attempts_returns_false() -> None:
    q = JobQueueManager(maxsize=4)
    job = Job(max_attempts=1, retry_on_failure=True)
    await q.enqueue(job)
    dq = await q.dequeue()
    assert q.nack(dq) is False


@pytest.mark.asyncio
async def test_recover_stale_tasks_requeues() -> None:
    q = JobQueueManager(maxsize=4, stale_after_seconds=-1.0)
    job = Job()
    await q.enqueue(job)
    await q.dequeue()
    assert q.in_flight_count() == 1
    requeued = await q.recover_stale_tasks()
    assert requeued == 1
    assert q.pending_qsize() == 1
