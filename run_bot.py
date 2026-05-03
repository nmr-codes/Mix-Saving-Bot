#!/usr/bin/env python3
"""Run Telegram bot + downloader workers (same process by default)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys

from aiogram import Bot

from bot.app import create_bot, setup_dispatcher
from bot.notifier import TelegramNotifier
from core.logging_setup import setup_json_logging
from core.settings import get_settings
from downloader.yt_dlp_downloader import YtDlpMediaDownloader

from core.contracts.types import QueueMessage
from services.cache.file_cache import FileCacheStore
from services.jobs.repository import InMemoryJobRepository
from services.jobs.service import JobServiceImpl
from services.jobs.terminal_waiter import JobTerminalWaiter
from services.queue.memory_queue import MemoryQueueConsumer, MemoryQueueProducer
from services.queue.protocols import QueueConsumer, QueueProducer
from services.worker_runner import run_worker_loop


async def main() -> None:
    settings = get_settings()
    if not settings.BOT_TOKEN.strip():
        print("Set MIX_BOT_TOKEN to your Telegram bot token.", file=sys.stderr)
        sys.exit(1)

    setup_json_logging(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))

    bot: Bot = create_bot(settings)
    notifier = TelegramNotifier(
        bot,
        document_upload_timeout_sec=settings.TELEGRAM_DOCUMENT_UPLOAD_TIMEOUT_SEC,
    )

    waiter = JobTerminalWaiter()
    job_service = JobServiceImpl(InMemoryJobRepository(), waiter=waiter)
    cache_store = FileCacheStore(settings.CACHE_ROOT_DIR)
    downloader_engine = YtDlpMediaDownloader(settings)

    producer: QueueProducer
    consumer: QueueConsumer
    queue_peek: asyncio.Queue[QueueMessage] | None

    if settings.QUEUE_BACKEND == "redis":
        if not settings.REDIS_URL:
            print("MIX_REDIS_URL is required when MIX_QUEUE_BACKEND=redis.", file=sys.stderr)
            sys.exit(1)
        from services.queue.redis_queue import RedisQueueConsumer as RConsumer
        from services.queue.redis_queue import RedisQueueProducer as RProducer

        producer = RProducer(settings.REDIS_URL, settings.REDIS_QUEUE_STREAM_KEY)
        consumer = RConsumer(
            settings.REDIS_URL,
            settings.REDIS_QUEUE_STREAM_KEY,
            settings.REDIS_QUEUE_GROUP,
            settings.REDIS_QUEUE_CONSUMER_NAME,
        )
        queue_peek = None
    else:
        q = asyncio.Queue(maxsize=512)
        producer = MemoryQueueProducer(q)
        consumer = MemoryQueueConsumer(q)
        queue_peek = q

    dp = setup_dispatcher(
        bot,
        notifier,
        settings,
        job_service=job_service,
        queue_producer=producer,
        waiter=waiter,
        queue_for_depth=queue_peek,
    )

    worker_stop = asyncio.Event()
    worker_task = asyncio.create_task(
        run_worker_loop(
            consumer,
            job_service,
            cache_store,
            downloader_engine,
            notifier,
            settings,
            stop_event=worker_stop,
        ),
        name="download-workers",
    )

    try:
        await dp.start_polling(bot)
    finally:
        worker_stop.set()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await worker_task
        with contextlib.suppress(Exception):
            await producer.close()
        with contextlib.suppress(Exception):
            await consumer.close()
        with contextlib.suppress(Exception):
            await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())


def run() -> None:
    asyncio.run(main())
