from __future__ import annotations

import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from core.logging_setup import get_logger

log = get_logger("bot.middleware.rate_limit")


class RateLimitMiddleware(BaseMiddleware):
    """Sliding-window per-user limit applied to Telegram updates."""

    def __init__(self, *, max_events: int, window_seconds: float) -> None:
        self._max = max(1, max_events)
        self._window = window_seconds
        self._hits: dict[int, deque[float]] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None or getattr(user, "is_bot", False):
            return await handler(event, data)

        now = time.monotonic()
        dq = self._hits.setdefault(user.id, deque())
        while dq and now - dq[0] > self._window:
            dq.popleft()

        if len(dq) >= self._max:
            log.warning(
                "rate limit hit",
                extra={"telegram_user_id": user.id, "hits": len(dq)},
            )
            if isinstance(event, Message):
                await event.answer("You are sending too many requests — please slow down.")
            elif isinstance(event, CallbackQuery):
                await event.answer(
                    "Too many actions — try again shortly.",
                    show_alert=True,
                )
            return None

        dq.append(now)
        return await handler(event, data)
