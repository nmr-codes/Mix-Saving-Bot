from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from core.contracts.types import QueueMessage

QueueHandler = Callable[[QueueMessage], Awaitable[None]]


class QueueProducer(Protocol):
    async def enqueue(self, msg: QueueMessage) -> None:
        ...

    async def close(self) -> None:
        ...


class QueueConsumer(Protocol):
    async def subscribe(self, handler: QueueHandler) -> None:
        ...

    async def close(self) -> None:
        ...
