from __future__ import annotations

import asyncio
import contextlib
import traceback
from collections.abc import Awaitable, Callable
from typing import Any

from services.logging_config import get_logger
from services.queue_manager import JobQueueManager, QueueOverflowError
from services.types import Job, JobStatus, TaskResult

log = get_logger("services.worker")

JobProcessor = Callable[[Job], Awaitable[TaskResult]]


class Worker:
    """Drains queue jobs until cancelled and publishes structured results."""

    def __init__(
        self,
        queue: JobQueueManager,
        *,
        processors: dict[str, JobProcessor],
        name: str = "worker-0",
    ) -> None:
        self.queue = queue
        self.processors = processors
        self.name = name

    async def run(self) -> None:
        log.info("worker started", extra={"worker": self.name})
        try:
            while True:
                job = await self.queue.dequeue()
                try:
                    result = await self._dispatch(job)
                except asyncio.CancelledError:
                    raise
                except BaseException:
                    tb = traceback.format_exc()
                    log.exception(
                        "processor crashed",
                        extra={"worker": self.name, "job_id": job.id},
                    )
                    result = TaskResult(
                        job_id=job.id,
                        status=JobStatus.FAILED,
                        message="Worker crash",
                        detail={"error_code": "WORKER_EXCEPTION", "traceback": tb},
                    )
                self.queue.publish_result(result)
                if result.status in (
                    JobStatus.COMPLETED,
                    JobStatus.REJECTED_DUPLICATE,
                    JobStatus.SKIPPED,
                ):
                    self.queue.acknowledge(job)
                elif job.retry_on_failure:
                    if not self.queue.nack(job):
                        log.warning(
                            "job retries exhausted",
                            extra={"worker": self.name, "job_id": job.id},
                        )
                else:
                    self.queue.acknowledge(job)
        finally:
            log.info("worker stopped", extra={"worker": self.name})

    async def _dispatch(self, job: Job) -> TaskResult:
        processor = self.processors.get(job.kind)
        if processor is None:
            return TaskResult(
                job_id=job.id,
                status=JobStatus.FAILED,
                message=f"No processor for kind {job.kind}",
                detail={"error_code": "NO_PROCESSOR"},
            )
        out = await processor(job)
        assert isinstance(out, TaskResult), "processors must return TaskResult"
        if out.job_id != job.id:
            return TaskResult(
                job_id=job.id,
                status=JobStatus.FAILED,
                message="Processor produced mismatched job_id",
                detail={"error_code": "PROCESSOR_BUG", "other_job_id": out.job_id},
            )
        return out


class WorkerPool:
    """Runs multiple ``Worker`` tasks against the shared ``JobQueueManager``."""

    def __init__(
        self,
        queue: JobQueueManager,
        *,
        processors: dict[str, JobProcessor],
        workers: int = 2,
        recover_interval_seconds: float = 30.0,
    ) -> None:
        self.queue = queue
        self.processors = processors
        self.workers = max(1, workers)
        self._recover_interval = recover_interval_seconds
        self._tasks: list[asyncio.Task[Any]] = []
        self._recovery_task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self._stop.clear()
        for i in range(self.workers):
            w = Worker(
                self.queue,
                processors=self.processors,
                name=f"worker-{i}",
            )
            self._tasks.append(asyncio.create_task(w.run()))
        self._recovery_task = asyncio.create_task(
            self._recover_loop(), name="job-queue-recovery"
        )

    async def _recover_loop(self) -> None:
        try:
            while not self._stop.is_set():
                await asyncio.sleep(self._recover_interval)
                try:
                    n = await self.queue.recover_stale_tasks()
                except QueueOverflowError:
                    log.error("stale recovery failed: queue overflow")
                    continue
                if n:
                    log.warning("requeued stale in-flight jobs", extra={"count": n})
        except asyncio.CancelledError:
            return

    async def stop(self) -> None:
        self._stop.set()
        self.queue.close()
        if self._recovery_task:
            self._recovery_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._recovery_task
            self._recovery_task = None
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
