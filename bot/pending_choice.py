"""Short-lived mappings for URL → Telegram reply targets (callback_token is compact)."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass


@dataclass(slots=True)
class PendingChoice:
    user_id: int
    url: str
    reply_to_message_id: int


class PendingChoiceStore:
    def __init__(self, ttl_seconds: float = 720.0) -> None:
        self._ttl = ttl_seconds
        self._entries: dict[str, tuple[float, PendingChoice]] = {}
        self._lock = asyncio.Lock()

    def _purge_unlocked(self, now: float) -> None:
        dead = [k for k, (expires_at, _) in self._entries.items() if expires_at < now]
        for key in dead:
            self._entries.pop(key, None)

    async def create(
        self, user_id: int, *, url: str, reply_to_message_id: int
    ) -> str:
        token = uuid.uuid4().hex
        now = time.monotonic()
        async with self._lock:
            self._purge_unlocked(now)
            self._entries[token] = (now + self._ttl, PendingChoice(user_id, url, reply_to_message_id))
        return token

    async def pop(self, token: str, user_id: int) -> PendingChoice | None:
        now = time.monotonic()
        async with self._lock:
            self._purge_unlocked(now)
            row = self._entries.pop(token, None)
        if row is None:
            return None
        expires_at, payload = row
        if expires_at < now or payload.user_id != user_id:
            return None
        return payload
