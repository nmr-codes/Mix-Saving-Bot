from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import CallbackQuery, Message

from bot.middleware.logging_mw import UpdateLoggingMiddleware
from bot.middleware.rate_limit import RateLimitMiddleware


@pytest.mark.asyncio
async def test_logging_middleware_delegates() -> None:
    mw = UpdateLoggingMiddleware()
    inner = AsyncMock(return_value={"ok": True})
    msg = MagicMock(spec=Message)
    msg.chat = MagicMock(id=9)
    msg.from_user = MagicMock(id=1, is_bot=False)
    msg.data = None
    out = await mw(inner, msg, {})
    assert out["ok"] is True
    inner.assert_awaited_once()


@pytest.mark.asyncio
async def test_rate_limit_allows_burst_then_blocks_messages() -> None:
    mw = RateLimitMiddleware(max_events=2, window_seconds=3_600.0)

    hits: list[bool] = []

    async def handler(_event: object, _data: dict) -> str:
        hits.append(True)
        return "ok"

    user = MagicMock(id=7, is_bot=False)
    event = MagicMock(spec=Message)
    event.from_user = user
    event.answer = AsyncMock()

    assert await mw(handler, event, {}) == "ok"
    assert await mw(handler, event, {}) == "ok"
    assert await mw(handler, event, {}) is None
    assert len(hits) == 2


@pytest.mark.asyncio
async def test_rate_limit_for_callback_queries() -> None:
    mw = RateLimitMiddleware(max_events=1, window_seconds=3_600.0)

    async def handler(_event: object, _data: dict) -> str:
        return "ok"

    user = MagicMock(id=77, is_bot=False)
    ev = MagicMock(spec=CallbackQuery)
    ev.from_user = user
    ev.answer = AsyncMock()

    assert await mw(handler, ev, {}) == "ok"
    assert await mw(handler, ev, {}) is None
    ev.answer.assert_awaited()
