from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from core.logging_setup import get_logger

log = get_logger("bot.middleware.logging")


class UpdateLoggingMiddleware(BaseMiddleware):
    """Structured logging for Telegram updates routed through the dispatcher."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        extra: dict[str, object] = {"event": type(event).__name__}

        fw = getattr(event, "from_user", None)
        if fw is not None:
            extra["telegram_user_id"] = fw.id
        chat = getattr(event, "chat", None)
        if chat is not None:
            extra["telegram_chat_id"] = chat.id
        cb_data = getattr(event, "data", None)
        if isinstance(cb_data, str):
            extra["telegram_callback_data_prefix"] = cb_data[:48]

        log.info("incoming telegram update", extra=extra)
        return await handler(event, data)
