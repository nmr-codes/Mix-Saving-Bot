from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from core.contracts.errors import DownloaderFatalError, DownloaderTransientError
from core.settings import Settings
from downloader import _sync_engine as sync
from downloader.protocols import (
    DownloadJobContext,
    DownloadProgress,
    DownloadProgressCallback,
)
from downloader.sanitize import validate_for_download
from yt_dlp.utils import DownloadError as YtDlpDownloadErrorRaw


class YtDlpMediaDownloader:
    """Async façade over threaded yt-dlp (see :mod:`downloader._sync_engine`)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._config_path = settings.YTDLP_CONFIG_PATH

    def _constraints_dict(self, ctx: DownloadJobContext) -> None:
        validate_for_download(ctx.source_url, ctx.constraints)

    async def probe(self, ctx: DownloadJobContext) -> dict[str, Any]:
        self._constraints_dict(ctx)
        loop = asyncio.get_running_loop()

        def _run() -> dict[str, Any]:
            wd = Path(tempfile.mkdtemp(prefix="mixdl-probe-"))
            try:
                info = sync.extract_info_only(
                    ctx.source_url,
                    work_dir=wd,
                    config_path=self._config_path,
                )
            finally:
                sync.cleanup_work_dir(wd, strict=True)
            return sync.slim_metadata(info)

        try:
            meta = await loop.run_in_executor(None, _run)
        except (
            sync.GeoBlockedError,
            sync.PrivateContentError,
            sync.InvalidURLError,
        ) as exc:
            raise DownloaderFatalError(str(exc)) from exc
        except sync.YtDlpDownloadError as exc:
            if exc.__class__ is sync.YtDlpDownloadError:
                raise DownloaderTransientError(str(exc)) from exc
            raise DownloaderFatalError(str(exc)) from exc
        except YtDlpDownloadErrorRaw as exc:
            raise DownloaderTransientError(str(exc)) from exc

        duration = meta.get("duration")
        if isinstance(duration, (int, float)) and duration > ctx.constraints.max_duration_sec:
            raise DownloaderFatalError(
                f"Media exceeds max duration ({ctx.constraints.max_duration_sec}s).",
            )
        return meta

    def _mode(self, ctx: DownloadJobContext) -> str:
        fmt = (ctx.requested_format_id or "").strip().lower()
        if fmt in ("audio", "mp3", "bestaudio"):
            return "audio"
        return "video"

    async def download(
        self,
        ctx: DownloadJobContext,
        on_progress: DownloadProgressCallback,
    ) -> list[dict[str, Any]]:
        await on_progress({"stage": "starting", "message": "starting"})
        self._constraints_dict(ctx)
        work = Path(ctx.work_dir)
        work.mkdir(parents=True, exist_ok=True)
        mode = self._mode(ctx)

        loop = asyncio.get_running_loop()

        ytdlp_hook = sync.build_ytdlp_progress_hook(
            ctx.job_id,
            ctx.source_url,
            log_full_every_hook=self._settings.DOWNLOAD_LOG_EVERY_PROGRESS,
        )

        def _sync_dl() -> tuple[Path, dict[str, Any]]:
            if mode == "audio":
                return sync.download_audio_sync(
                    ctx.source_url,
                    work_dir=work,
                    config_path=self._config_path,
                    progress_hook=ytdlp_hook,
                )
            return sync.download_video_sync(
                ctx.source_url,
                work_dir=work,
                config_path=self._config_path,
                progress_hook=ytdlp_hook,
            )

        await on_progress({"stage": "downloading", "message": "download"})
        try:
            outfile, slim = await loop.run_in_executor(None, _sync_dl)
        except (
            sync.GeoBlockedError,
            sync.PrivateContentError,
            sync.InvalidURLError,
        ) as exc:
            raise DownloaderFatalError(str(exc)) from exc
        except sync.YtDlpDownloadError as exc:
            if exc.__class__ is sync.YtDlpDownloadError:
                raise DownloaderTransientError(str(exc)) from exc
            raise DownloaderFatalError(str(exc)) from exc
        except YtDlpDownloadErrorRaw as exc:
            raise DownloaderTransientError(str(exc)) from exc

        size = outfile.stat().st_size
        if size > ctx.constraints.max_file_size_bytes:
            raise DownloaderFatalError("Downloaded file exceeds configured size limit.")
        await on_progress({"stage": "finished", "pct": 100.0})

        item: dict[str, Any] = {
            "local_path": str(outfile.resolve()),
            "title": slim.get("title"),
            "duration_sec": slim.get("duration"),
            "mime_type": (
                "audio/mpeg"
                if mode == "audio"
                else ("video/mp4" if outfile.suffix.lower() == ".mp4" else "application/octet-stream")
            ),
        }
        return [item]


def temp_work_dir(job_id: str) -> Path:
    base = Path(tempfile.gettempdir()).resolve()
    return Path(tempfile.mkdtemp(prefix=f"mixdl-{job_id}-", dir=str(base)))
