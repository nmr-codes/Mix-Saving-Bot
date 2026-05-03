from __future__ import annotations

import asyncio

import pytest

from core.contracts.types import QueueMessage
from services.queue.memory_queue import MemoryQueueConsumer, MemoryQueueProducer


@pytest.mark.asyncio
async def test_memory_queue_delivery_order() -> None:
    q: asyncio.Queue[QueueMessage] = asyncio.Queue()
    prod = MemoryQueueProducer(q)
    consumer = MemoryQueueConsumer(q)
    received: list[str] = []

    async def h(msg: QueueMessage) -> None:
        received.append(msg["job_id"])

    worker = asyncio.create_task(consumer.subscribe(h))

    await prod.enqueue(
        {"job_id": "a", "correlation_id": "c1", "enqueued_at_unix": 1.0}
    )
    await prod.enqueue(
        {"job_id": "b", "correlation_id": "c2", "enqueued_at_unix": 2.0}
    )

    for _ in range(200):
        if received == ["a", "b"]:
            break
        await asyncio.sleep(0.02)

    worker.cancel()
    with pytest.raises(asyncio.CancelledError):
        await worker

    await prod.close()
    await consumer.close()
    assert received == ["a", "b"]
