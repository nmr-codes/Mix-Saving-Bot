from __future__ import annotations

import asyncio
import threading
import time

from services.types import Job, TaskResult


class QueueOverflowError(Exception):
    """Raised when the bounded queue rejects a new ``Job`` or a requeue fails."""


class QueueClosedError(RuntimeError):
    """Raised after the manager stops accepting submissions."""


class JobQueueManager:
    """
    In-process asyncio job queue wired to waiter futures.

    Callers awaiting results must publish the same ``job.id`` that workers use
    when delivering ``TaskResult`` via :meth:`publish_result`.

    In-flight jobs are tracked so :meth:`recover_stale_tasks` can requeue work
    after a worker crash; use :meth:`nack` for bounded retries on failure.
    """

    def __init__(
        self,
        *,
        maxsize: int = 256,
        stale_after_seconds: float = 600.0,
    ) -> None:
        self._queue: asyncio.Queue[Job] = asyncio.Queue(maxsize=maxsize)
        self._waiters: dict[str, asyncio.Future[TaskResult]] = {}
        self._closed = False
        self._in_flight: dict[str, tuple[Job, float]] = {}
        self._flight_lock = threading.Lock()
        self._stale_after = stale_after_seconds
        self._maxsize = maxsize

    @property
    def maxsize(self) -> int:
        return self._maxsize

    async def enqueue(self, job: Job) -> None:
        if self._closed:
            raise QueueClosedError("queue closed")
        try:
            self._queue.put_nowait(job)
        except asyncio.QueueFull as exc:
            raise QueueOverflowError("queue overflow") from exc

    async def dequeue(self) -> Job:
        job = await self._queue.get()
        with self._flight_lock:
            self._in_flight[job.id] = (job, time.monotonic())
        return job

    def acknowledge(self, job: Job) -> None:
        with self._flight_lock:
            self._in_flight.pop(job.id, None)
        self._queue.task_done()

    def nack(self, job: Job) -> bool:
        """
        Return ``job`` to the pending queue after a failed attempt.

        Pairs with one prior :meth:`dequeue` for this attempt (calls
        :meth:`asyncio.Queue.task_done` exactly once). Returns ``False`` if
        retries are exhausted or the queue is closed.
        """
        with self._flight_lock:
            self._in_flight.pop(job.id, None)
        self._queue.task_done()

        job.attempts += 1
        if job.attempts >= job.max_attempts or self._closed:
            return False
        try:
            self._queue.put_nowait(job)
        except asyncio.QueueFull as exc:
            raise QueueOverflowError("queue overflow on nack") from exc
        return True

    async def recover_stale_tasks(self) -> int:
        """Requeue in-flight jobs older than ``stale_after_seconds``."""
        now = time.monotonic()
        to_requeue: list[Job] = []
        with self._flight_lock:
            for jid, (job, started) in list(self._in_flight.items()):
                if now - started > self._stale_after:
                    del self._in_flight[jid]
                    to_requeue.append(job)

        requeued = 0
        for job in to_requeue:
            if self._closed:
                break
            self._queue.task_done()
            try:
                self._queue.put_nowait(job)
                requeued += 1
            except asyncio.QueueFull as exc:
                with self._flight_lock:
                    self._in_flight[job.id] = (job, time.monotonic())
                raise QueueOverflowError(
                    "queue overflow while recovering stale tasks"
                ) from exc
        return requeued

    def close(self) -> None:
        self._closed = True

    async def enqueue_and_wait(
        self, job: Job, *, timeout: float | None = None
    ) -> TaskResult:
        """
        Register the waiter **before** the job enters the FIFO so workers cannot
        complete faster than observability attaches.
        """
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[TaskResult] = loop.create_future()
        self._waiters[job.id] = fut
        try:
            await self.enqueue(job)
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._waiters.pop(job.id, None)

    def publish_result(self, result: TaskResult) -> None:
        waiter = self._waiters.pop(result.job_id, None)
        if waiter is None or waiter.done():
            return
        waiter.set_result(result)

    async def abandon_wait_if_pending(self, job_id: str) -> None:
        fut = self._waiters.pop(job_id, None)
        if fut and not fut.done():
            fut.cancel()

    @property
    def closed(self) -> bool:
        return self._closed

    async def idle_join(self, timeout: float | None = None) -> None:
        await asyncio.wait_for(self._queue.join(), timeout=timeout)

    def pending_qsize(self) -> int:
        return self._queue.qsize()

    def in_flight_count(self) -> int:
        with self._flight_lock:
            return len(self._in_flight)
