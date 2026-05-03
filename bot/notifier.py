from __future__ import annotations

from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile

from core.contracts.types import JobRecord
from core.logging_setup import get_logger

log = get_logger("bot.notifier")

# Bot API practical limit for free uploads (~50 MiB).
MAX_DOCUMENT_BYTES = 49 * 1024 * 1024

_TELEGRAM_FILENAME_MAX = 180


def _outgoing_document_filename(job: JobRecord, path: Path, *, mime_hint: str | None) -> str:
    """Force .mp4 for video / .mp3 for audio in the Telegram attachment name."""
    if mime_hint == "audio/mpeg":
        ext = ".mp3"
    elif mime_hint == "video/mp4":
        ext = ".mp4"
    else:
        fmt = (job["request"].get("requested_format_id") or "video").strip().lower()
        ext = ".mp3" if fmt in ("audio", "mp3", "bestaudio") else ".mp4"

    stem = (path.stem or "media").strip().replace("/", "_").replace("\\", "_")
    max_stem = max(1, _TELEGRAM_FILENAME_MAX - len(ext))
    if len(stem) > max_stem:
        stem = stem[:max_stem]
    return f"{stem}{ext}"


class TelegramNotifier:
    def __init__(
        self,
        bot: Bot,
        *,
        document_upload_timeout_sec: int = 300,
    ) -> None:
        self._bot = bot
        self._document_upload_timeout_sec = document_upload_timeout_sec

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
            fname = _outgoing_document_filename(
                job,
                path,
                mime_hint=primary.get("mime_type") if isinstance(primary.get("mime_type"), str) else None,
            )
            doc = FSInputFile(path=str(path), filename=fname)
            await self._bot.send_document(
                document=doc,
                request_timeout=self._document_upload_timeout_sec,
                **kwargs,
            )
            return

        if status == "failed":
            msg = job.get("error_message_safe") or "Download failed."
            await self._bot.send_message(text=msg, **kwargs)
            return

        log.debug(
            "non-terminal notifier call",
            extra={"job_id": job["job_id"], "status": status},
        )
