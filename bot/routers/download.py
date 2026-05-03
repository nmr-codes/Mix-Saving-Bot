from __future__ import annotations

import asyncio
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Protocol

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from bot import formatters
from bot.keyboards import build_download_choice_keyboard
from bot.pending_choice import PendingChoiceStore
from core.contracts.errors import SanitizeError
from core.contracts.types import QueueMessage, SubmitDownloadRequest
from core.observability import get_metrics
from core.settings import Settings
from downloader.protocols import DownloadConstraints
from downloader.sanitize import canonical_cache_key, validate_for_download

from services.jobs.service import JobServiceImpl
from services.jobs.terminal_waiter import JobTerminalWaiter
from services.queue.protocols import QueueProducer

_URL_RE = re.compile(
    r"https?://[^\s<>\"]+",
    re.IGNORECASE,
)


class _QueuePeek(Protocol):
    def pending_qsize(self) -> int:
        ...


def build_download_router(
    *,
    settings: Settings,
    jobs: JobServiceImpl,
    producer: QueueProducer,
    waiter: JobTerminalWaiter,
    queue_peek: _QueuePeek | None = None,
) -> Router:
    r = Router(name="download")
    pending_store = PendingChoiceStore()

    def _constraints() -> DownloadConstraints:
        return DownloadConstraints(
            max_duration_sec=settings.MAX_DURATION_SEC,
            max_file_size_bytes=settings.MAX_OUTPUT_BYTES,
            allowed_hosts=settings.ALLOWED_HOSTS,
        )

    async def enqueue_download_job(
        send_user_notice: Callable[..., Awaitable[object]],
        *,
        chat_id: int,
        user_id: int,
        reply_to_message_id: int,
        source_url: str,
        format_id: str | None,
    ) -> None:
        if queue_peek and queue_peek.pending_qsize() >= settings.HIGH_WATER_QUEUE_DEPTH:
            await send_user_notice(formatters.fmt_busy())
            return

        try:
            validate_for_download(source_url, _constraints())
        except SanitizeError as exc:
            await send_user_notice(str(exc))
            return

        correlation_id = uuid.uuid4().hex
        req: SubmitDownloadRequest = {
            "source_url": source_url,
            "correlation_id": correlation_id,
            "chat": {
                "chat_id": chat_id,
                "user_id": user_id,
                "reply_to_message_id": reply_to_message_id,
            },
        }
        if format_id:
            req["requested_format_id"] = format_id

        key = f"{chat_id}:{canonical_cache_key(source_url, format_id)}"
        rec, should_enqueue = await jobs.submit(req, dedupe_key=key)
        fut = await waiter.subscribe(rec["job_id"], snapshot=rec)
        await send_user_notice(formatters.fmt_queued(rec["job_id"]))
        await get_metrics().inc("jobs_submitted_total")

        if should_enqueue:
            msg: QueueMessage = {
                "job_id": rec["job_id"],
                "correlation_id": correlation_id,
                "enqueued_at_unix": time.time(),
            }
            await producer.enqueue(msg)

        try:
            await asyncio.wait_for(
                fut,
                timeout=float(settings.DOWNLOAD_DEADLINE_SEC + 120),
            )
        except asyncio.TimeoutError:
            await send_user_notice(formatters.fmt_timeout())

    @r.message(CommandStart())
    async def cmd_start(message: Message) -> None:
        await message.answer(
            "Send a media link — I'll ask whether you want video or audio.\n"
            "You can also skip the menu with /video or /audio followed by the link.",
        )

    @r.message(Command("help"))
    async def cmd_help(message: Message) -> None:
        await cmd_start(message)

    @r.message(Command("audio"))
    async def cmd_audio(message: Message) -> None:
        if not message.from_user:
            return
        text = message.text or ""
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await message.answer("Usage: /audio <url>")
            return
        url = parts[1].strip()
        await enqueue_download_job(
            message.answer,
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            reply_to_message_id=message.message_id,
            source_url=url,
            format_id="audio",
        )

    @r.message(Command("video"))
    async def cmd_video(message: Message) -> None:
        if not message.from_user:
            return
        text = message.text or ""
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await message.answer("Usage: /video <url>")
            return
        url = parts[1].strip()
        await enqueue_download_job(
            message.answer,
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            reply_to_message_id=message.message_id,
            source_url=url,
            format_id="video",
        )

    @r.message(
        lambda m: bool(m.text)
        and not m.text.startswith("/")
        and ("http://" in m.text or "https://" in m.text)
    )
    async def implicit_url_prompt(message: Message) -> None:
        if not message.from_user:
            return
        raw = message.text or ""
        m_url = _URL_RE.search(raw)
        if m_url is None:
            await message.answer("I could not find an http(s) URL in that message.")
            return

        url = m_url.group(0).rstrip(").,]}")
        try:
            validate_for_download(url, _constraints())
        except SanitizeError as exc:
            await message.answer(str(exc))
            return

        token = await pending_store.create(
            message.from_user.id,
            url=url,
            reply_to_message_id=message.message_id,
        )
        await message.answer(
            "Choose what to download:",
            reply_markup=build_download_choice_keyboard(token),
        )

    @r.callback_query(F.data.startswith("dl:"))
    async def implicit_url_commit(query: CallbackQuery) -> None:
        if query.from_user is None or query.data is None:
            return

        parts = query.data.split(":", 2)
        if len(parts) != 3 or parts[0] != "dl":
            await query.answer()
            return

        kind, token = parts[1], parts[2]
        if kind not in {"v", "a"}:
            await query.answer()
            return

        payload = await pending_store.pop(token, query.from_user.id)
        if payload is None:
            await query.answer(
                "This menu expired — send your link again.",
                show_alert=True,
            )
            return

        await query.answer()
        if query.message is None:
            return
        await query.message.edit_reply_markup(reply_markup=None)

        fmt_id = "video" if kind == "v" else "audio"
        chat_id = query.message.chat.id

        async def _say(text: str) -> None:
            await query.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_to_message_id=payload.reply_to_message_id,
            )

        await enqueue_download_job(
            _say,
            chat_id=chat_id,
            user_id=payload.user_id,
            reply_to_message_id=payload.reply_to_message_id,
            source_url=payload.url,
            format_id=fmt_id,
        )

    return r
