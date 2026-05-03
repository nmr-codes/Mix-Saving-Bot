from __future__ import annotations

import contextlib
import time
from typing import Any

from core.contracts.types import QueueMessage
from core.logging_setup import get_logger
from services.queue.protocols import QueueHandler

log = get_logger("services.queue.redis")

try:
    from redis import asyncio as redis_async
except ImportError:  # pragma: no cover
    redis_async = None


class RedisQueueProducer:
    def __init__(self, redis_url: str, stream_key: str) -> None:
        if redis_async is None:
            raise RuntimeError("redis package is required for Redis queue backend")
        self._client = redis_async.from_url(redis_url, decode_responses=True)
        self._stream_key = stream_key

    async def enqueue(self, msg: QueueMessage) -> None:
        fields = {
            "job_id": msg["job_id"],
            "correlation_id": msg["correlation_id"],
            "enqueued_at_unix": str(msg["enqueued_at_unix"]),
        }
        await self._client.xadd(self._stream_key, fields)

    async def close(self) -> None:
        await self._client.aclose()


class RedisQueueConsumer:
    def __init__(
        self,
        redis_url: str,
        stream_key: str,
        group: str,
        consumer_name: str,
    ) -> None:
        if redis_async is None:
            raise RuntimeError("redis package is required for Redis queue backend")
        self._client = redis_async.from_url(redis_url, decode_responses=True)
        self._stream_key = stream_key
        self._group = group
        self._consumer_name = consumer_name
        self._closed = False

    async def _ensure_group(self) -> None:
        with contextlib.suppress(Exception):
            await self._client.xgroup_create(
                name=self._stream_key,
                groupname=self._group,
                id="0",
                mkstream=True,
            )

    async def subscribe(self, handler: QueueHandler) -> None:
        await self._ensure_group()
        while not self._closed:
            resp = await self._client.xreadgroup(
                groupname=self._group,
                consumername=self._consumer_name,
                streams={self._stream_key: ">"},
                count=1,
                block=5000,
            )
            if not resp:
                continue
            _stream_name, entries = resp[0]
            for entry_id, data in entries:
                try:
                    msg = _parse_message(data)
                    await handler(msg)
                    await self._client.xack(self._stream_key, self._group, entry_id)
                except Exception:
                    log.exception(
                        "handler failed; message not acked",
                        extra={"entry_id": entry_id},
                    )

    async def close(self) -> None:
        self._closed = True
        await self._client.aclose()


def _parse_message(data: dict[str, Any]) -> QueueMessage:
    return {
        "job_id": str(data.get("job_id", "")),
        "correlation_id": str(data.get("correlation_id", "")),
        "enqueued_at_unix": float(data.get("enqueued_at_unix", time.time())),
    }