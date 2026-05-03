from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from bot.middleware.logging_mw import UpdateLoggingMiddleware
from bot.middleware.rate_limit import RateLimitMiddleware
from bot.notifier import TelegramNotifier
from bot.routers.download import build_download_router
from core.contracts.types import QueueMessage
from core.settings import Settings
from services.jobs.service import JobServiceImpl
from services.jobs.terminal_waiter import JobTerminalWaiter
from services.queue.protocols import QueueProducer


def create_bot(settings: Settings) -> Bot:
    return Bot(
        settings.BOT_TOKEN,
        default=DefaultBotProperties(),
    )


def setup_dispatcher(
    bot: Bot,
    notifier: TelegramNotifier,
    settings: Settings,
    *,
    job_service: JobServiceImpl,
    queue_producer: QueueProducer,
    waiter: JobTerminalWaiter,
    queue_for_depth: asyncio.Queue[QueueMessage] | None,
) -> Dispatcher:
    dp = Dispatcher()
    dp.update.outer_middleware(UpdateLoggingMiddleware())
    dp.update.outer_middleware(
        RateLimitMiddleware(
            max_events=settings.RATE_LIMIT_MAX_EVENTS,
            window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
        )
    )
    dp["settings"] = settings
    dp["notifier"] = notifier
    dp["bot_instance"] = bot

    class _Peek:
        __slots__ = ("_q",)

        def __init__(self, q: asyncio.Queue[QueueMessage]) -> None:
            self._q = q

        def pending_qsize(self) -> int:
            return self._q.qsize()

    peek = _Peek(queue_for_depth) if queue_for_depth is not None else None
    dp.include_router(
        build_download_router(
            settings=settings,
            jobs=job_service,
            producer=queue_producer,
            waiter=waiter,
            queue_peek=peek,
        )
    )
    return dp
