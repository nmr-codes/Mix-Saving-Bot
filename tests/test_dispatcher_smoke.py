from __future__ import annotations

import asyncio

import pytest
from aiogram import Bot

from bot.app import create_bot, setup_dispatcher
from bot.notifier import TelegramNotifier
from core.settings import clear_settings_cache, get_settings
from services.jobs.repository import InMemoryJobRepository
from services.jobs.service import JobServiceImpl
from services.jobs.terminal_waiter import JobTerminalWaiter
from services.queue.memory_queue import MemoryQueueProducer


@pytest.mark.asyncio
async def test_setup_dispatcher_wires_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MIX_BOT_TOKEN", "123456789:TEST_TOKEN_NOT_REAL")
    clear_settings_cache()
    settings = get_settings()

    bot: Bot = create_bot(settings)
    notifier = TelegramNotifier(bot)
    waiter = JobTerminalWaiter()
    jobs = JobServiceImpl(InMemoryJobRepository(), waiter=waiter)
    q: asyncio.Queue = asyncio.Queue()
    producer = MemoryQueueProducer(q)

    dp = setup_dispatcher(
        bot,
        notifier,
        settings,
        job_service=jobs,
        queue_producer=producer,
        waiter=waiter,
        queue_for_depth=q,
    )
    assert dp is not None
    assert dp["settings"] is settings

    await producer.close()
    await bot.session.close()
