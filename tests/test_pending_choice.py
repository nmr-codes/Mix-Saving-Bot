from __future__ import annotations

import pytest

from bot.pending_choice import PendingChoiceStore


@pytest.mark.asyncio
async def test_pending_choice_roundtrip() -> None:
    s = PendingChoiceStore(ttl_seconds=600.0)
    tok = await s.create(
        user_id=5,
        url="https://youtube.com/watch?v=abc",
        reply_to_message_id=42,
    )
    assert len(tok) == 32
    payload = await s.pop(tok, 5)
    assert payload is not None
    assert payload.url.endswith("youtube.com/watch?v=abc")
    assert payload.reply_to_message_id == 42
    dup = await s.pop(tok, 5)
    assert dup is None


@pytest.mark.asyncio
async def test_pending_choice_wrong_user() -> None:
    s = PendingChoiceStore(ttl_seconds=600.0)
    tok = await s.create(1, url="https://a", reply_to_message_id=1)
    assert await s.pop(tok, 999) is None
