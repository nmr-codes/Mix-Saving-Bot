from __future__ import annotations

from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile

from core.contracts.types import JobRecord
from core.logging_setup import get_logger

log = get_logger("bot.notifier")

# Bot API practical limit for free uploads (~50 MiB).
MAX_DOCUMENT_BYTES = 49 * 1024 * 1024


class TelegramNotifier:
    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def notify_job_update(self, job: JobRecord) -> None:
        chat_id = job["request"]["chat"]["chat_id"]
        user_message_id = job["request"]["chat"].get("reply_to_message_id")
        status = job["status"]

        kwargs: dict = {"chat_id": chat_id}
        if isinstance(user_message_id, int):
            kwargs["reply_to_message_id"] = user_message_id

        if status == "succeeded":
            outs = job.get("outputs") or []
            if not outs:
                await self._bot.send_message(text="Done, but no file was attached.", **kwargs)
                return
            primary = outs[0]
            if primary["kind"] != "local_path":
                await self._bot.send_message(text=f"Done: {primary['value']}", **kwargs)
                return
            path = Path(primary["value"])
            if not path.is_file():
                await self._bot.send_message(text="Download finished but the file is missing.", **kwargs)
                return
            size = path.stat().st_size
            if size > MAX_DOCUMENT_BYTES:
                await self._bot.send_message(
                    text=(
                        "File is too large to send via Telegram Bot API "
                        f"({size // (1024 * 1024)} MiB). Try audio mode or a shorter video."
                    ),
                    **kwargs,
                )
                return
            fname = path.name
            doc = FSInputFile(path=str(path), filename=fname)
            await self._bot.send_document(document=doc, **kwargs)
            return

        if status == "failed":
            msg = job.get("error_message_safe") or "Download failed."
            await self._bot.send_message(text=msg, **kwargs)
            return

        log.debug(
            "non-terminal notifier call",
            extra={"job_id": job["job_id"], "status": status},
        )
