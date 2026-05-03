from __future__ import annotations

import asyncio

from core.contracts.types import QueueMessage
from services.queue.protocols import QueueHandler


class MemoryQueueProducer:
    def __init__(self, q: asyncio.Queue[QueueMessage]) -> None:
        self._q = q
        self._closed = False

    async def enqueue(self, msg: QueueMessage) -> None:
        if self._closed:
            raise RuntimeError("queue producer closed")
        await self._q.put(msg)

    async def close(self) -> None:
        self._closed = True


class MemoryQueueConsumer:
    def __init__(self, q: asyncio.Queue[QueueMessage]) -> None:
        self._q = q
        self._closed = False

    async def subscribe(self, handler: QueueHandler) -> None:
        while not self._closed:
            msg = await self._q.get()
            try:
                await handler(msg)
            finally:
                self._q.task_done()

    async def close(self) -> None:
        self._closed = True
