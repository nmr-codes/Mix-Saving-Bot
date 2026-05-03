from __future__ import annotations

import pytest

from services.pipeline import TaskPipeline
from services.queue_manager import QueueOverflowError
from services.dedupe_cache import DownloadCache
from services.types import Job, JobStatus, TaskResult


class FakeQueueSuccess:
    def __init__(self) -> None:
        self.jobs: list[Job] = []

    async def enqueue_and_wait(
        self, job: Job, *, timeout: float | None = None
    ) -> TaskResult:
        self.jobs.append(job)
        _ = timeout
        return TaskResult(job_id=job.id, status=JobStatus.COMPLETED, message="ok")


@pytest.mark.asyncio
async def test_submit_download_without_cache() -> None:
    fq = FakeQueueSuccess()
    pl = TaskPipeline(queue=fq)  # type: ignore[arg-type]
    out = await pl.submit_download(url="https://youtube.com/watch?v=z", media="video")
    assert out.status == JobStatus.COMPLETED
    assert fq.jobs and fq.jobs[0].payload["url"] == "https://youtube.com/watch?v=z"


@pytest.mark.asyncio
async def test_submit_download_duplicate_rejected() -> None:
    fq = FakeQueueSuccess()
    cache = DownloadCache()
    pl = TaskPipeline(queue=fq, cache=cache)  # type: ignore[arg-type]
    first = await pl.submit_download(url="https://x.com/u", media="audio")
    assert first.status != JobStatus.REJECTED_DUPLICATE

    dup = await pl.submit_download(url="https://x.com/u", media="audio")
    assert dup.status == JobStatus.REJECTED_DUPLICATE
    assert dup.detail.get("error_code") == "DUPLICATE"


@pytest.mark.asyncio
async def test_submit_download_overflow_aborts_reservation() -> None:
    calls = 0

    class FlakyQ:
        async def enqueue_and_wait(
            self, job: Job, *, timeout: float | None = None
        ) -> TaskResult:
            nonlocal calls
            calls += 1
            _ = timeout
            if calls == 1:
                raise QueueOverflowError()
            return TaskResult(job_id=job.id, status=JobStatus.COMPLETED)

    cache = DownloadCache()
    pl = TaskPipeline(queue=FlakyQ(), cache=cache)  # type: ignore[arg-type]

    with pytest.raises(QueueOverflowError):
        await pl.submit_download(url="https://y.com/q", media="video")

    after = await pl.submit_download(url="https://y.com/q", media="video")
    assert after.status == JobStatus.COMPLETED
    assert calls == 2
