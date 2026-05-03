from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from bot.notifier import MAX_DOCUMENT_BYTES, TelegramNotifier


@pytest.mark.asyncio
async def test_notifier_skips_when_file_too_large(tmp_path: Path) -> None:
    blob = tmp_path / "big.bin"
    with blob.open("wb") as f:
        f.seek(MAX_DOCUMENT_BYTES + 100)
        f.write(b"\0")

    job = {
        "job_id": "j",
        "status": "succeeded",
        "request": {
            "source_url": "u",
            "correlation_id": "c",
            "chat": {"chat_id": 5, "user_id": 6, "reply_to_message_id": 9},
        },
        "created_at_unix": 0,
        "updated_at_unix": 0,
        "outputs": [{"kind": "local_path", "value": str(blob), "byte_size": MAX_DOCUMENT_BYTES + 100}],
    }

    bot = AsyncMock()
    await TelegramNotifier(bot).notify_job_update(job)  # type: ignore[arg-type]
    bot.send_document.assert_not_called()
    bot.send_message.assert_awaited()


@pytest.mark.asyncio
async def test_notifier_sends_document_for_small_file(tmp_path: Path) -> None:
    p = tmp_path / "t.bin"
    p.write_bytes(b"abc")
    job = {
        "job_id": "j",
        "status": "succeeded",
        "request": {
            "source_url": "u",
            "correlation_id": "c",
            "chat": {"chat_id": 5, "user_id": 6},
        },
        "created_at_unix": 0,
        "updated_at_unix": 0,
        "outputs": [{"kind": "local_path", "value": str(p), "byte_size": 3}],
    }
    bot = AsyncMock()
    await TelegramNotifier(bot).notify_job_update(job)  # type: ignore[arg-type]
    bot.send_document.assert_awaited()
    assert bot.send_document.call_args.kwargs.get("request_timeout") == 300
    doc = bot.send_document.call_args.kwargs["document"]
    assert doc.filename == "t.mp4"


@pytest.mark.asyncio
async def test_notifier_audio_attachment_named_mp3(tmp_path: Path) -> None:
    p = tmp_path / "track.bin"
    p.write_bytes(b"abc")
    job = {
        "job_id": "j",
        "status": "succeeded",
        "request": {
            "source_url": "u",
            "correlation_id": "c",
            "chat": {"chat_id": 5, "user_id": 6},
            "requested_format_id": "audio",
        },
        "created_at_unix": 0,
        "updated_at_unix": 0,
        "outputs": [
            {"kind": "local_path", "value": str(p), "byte_size": 3, "mime_type": "audio/mpeg"}
        ],
    }
    bot = AsyncMock()
    await TelegramNotifier(bot).notify_job_update(job)  # type: ignore[arg-type]
    doc = bot.send_document.call_args.kwargs["document"]
    assert doc.filename == "track.mp3"
