"""
Synchronous yt-dlp engine; used from :class:`YtDlpMediaDownloader` via ``asyncio.to_thread``.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError as YtDlpDownloadErrorRaw

from core.logging_setup import get_logger


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_ytdlp_config_path(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    env = os.environ.get("MIX_SAVING_YTDLP_CONFIG")
    if env:
        return Path(env).expanduser().resolve()
    bundled = Path(__file__).resolve().parent / "yt-dlp.conf"
    if bundled.is_file():
        return bundled
    return project_root() / "config" / "yt-dlp.conf"


class YtDlpDownloadError(Exception):
    def __init__(
        self,
        message: str,
        *,
        url: str | None = None,
        original: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.url = url
        self.original = original


class InvalidURLError(YtDlpDownloadError):
    pass


class PrivateContentError(YtDlpDownloadError):
    pass


class GeoBlockedError(YtDlpDownloadError):
    pass


def _validate_http_url(url: str) -> None:
    from urllib.parse import urlparse

    if not url or not isinstance(url, str):
        raise InvalidURLError("URL is empty", url=url)
    trimmed = url.strip()
    if not trimmed:
        raise InvalidURLError("URL is whitespace only", url=url)
    parsed = urlparse(trimmed)
    if parsed.scheme not in ("http", "https"):
        raise InvalidURLError(
            f"URL must use http or https scheme, got {parsed.scheme!r}",
            url=trimmed,
        )
    if not parsed.netloc:
        raise InvalidURLError("URL has no host", url=trimmed)


def _classify_message(msg: str) -> type[YtDlpDownloadError] | None:
    lower = msg.lower()
    if any(
        p in lower
        for p in (
            "not available in your country",
            "not made this video available in your country",
            "country availability",
            "blocked in your country",
            "geo-restricted",
            "georestricted",
        )
    ) or ("geo" in lower and "restrict" in lower):
        return GeoBlockedError
    if any(
        p in lower
        for p in (
            "this is a private video",
            "private video",
            "sign in to confirm",
            "login required",
            "requires authentication",
            "age-gated",
            "age verification",
            "copyright",
            "removed by the uploader",
            "no longer available",
        )
    ):
        return PrivateContentError
    if any(
        p in lower
        for p in (
            "unsupported url",
            "no suitable extractor",
            "unable to extract",
            "invalid argument",
        )
    ):
        return InvalidURLError
    return None


def _raise_mapped_download_error(url: str, exc: YtDlpDownloadErrorRaw) -> None:
    msg = str(exc) or getattr(exc, "msg", "") or repr(exc)
    category = _classify_message(msg)
    if category is not None:
        raise category(msg, url=url, original=exc) from exc
    raise YtDlpDownloadError(msg, url=url, original=exc) from exc


def _pct_from_progress_dict(d: dict[str, Any]) -> float | None:
    total = d.get("total_bytes") or d.get("total_bytes_estimate")
    downloaded = d.get("downloaded_bytes")
    if isinstance(total, (int, float)) and isinstance(downloaded, (int, float)) and total > 0:
        return round(100.0 * downloaded / total, 2)
    return None


def build_ytdlp_progress_hook(
    job_id: str | None,
    source_url: str,
    *,
    log_full_every_hook: bool = False,
) -> Callable[[dict[str, Any]], None]:
    """
    Log yt-dlp ``progress_hooks`` payloads. When ``log_full_every_hook`` is True,
    every hook emits INFO with the full dict; otherwise INFO is throttled and DEBUG
    carries every update (use ``MIX_LOG_LEVEL=DEBUG``).
    """
    log = get_logger("downloader.ytdlp")
    last_info = 0.0
    last_info_pct = -100.0

    def hook(d: dict[str, Any]) -> None:
        nonlocal last_info, last_info_pct
        now = time.monotonic()
        status = d.get("status")
        pct = _pct_from_progress_dict(d)

        extra_base: dict[str, Any] = {
            "job_id": job_id,
            "source_url": source_url,
            "ytdlp_progress": d,
        }

        if log_full_every_hook:
            log.info("yt-dlp progress", extra=extra_base)
            return

        log.debug("yt-dlp progress", extra=extra_base)

        emit_info = False
        if status != "downloading":
            emit_info = True
        elif pct is None:
            emit_info = (now - last_info) >= 2.0
        else:
            if pct - last_info_pct >= 10.0 or (now - last_info) >= 3.0:
                emit_info = True
                last_info_pct = pct

        if emit_info:
            last_info = now
            log.info("yt-dlp progress", extra=extra_base)

    return hook


def _build_common_ydl_opts(
    work_dir: Path,
    *,
    config_path: Path | None,
) -> dict[str, Any]:
    cfg = config_path if config_path is not None else default_ytdlp_config_path()
    locations: list[str] = [str(cfg)] if cfg.is_file() else []

    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "outtmpl": str(work_dir / "%(id)s_%(title).100B.%(ext)s"),
        "paths": {"home": str(work_dir), "temp": str(work_dir)},
        "windowsfilenames": False,
        "ignoreerrors": False,
        "noprogress": True,
        "retries": 10,
        "fragment_retries": 10,
        "socket_timeout": 45,
    }
    if locations:
        opts["config_locations"] = locations

    ff = os.environ.get("MIX_SAVING_FFMPEG_LOCATION")
    if ff:
        opts["ffmpeg_location"] = ff

    cookies = os.environ.get("MIX_SAVING_YTDLP_COOKIESFILE")
    if cookies and Path(cookies).is_file():
        opts["cookiefile"] = cookies

    return opts


def slim_metadata(info: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "id",
        "title",
        "extractor",
        "extractor_key",
        "webpage_url",
        "duration",
        "width",
        "height",
        "ext",
        "format_id",
        "playlist_count",
    )
    out: dict[str, Any] = {}
    for k in keys:
        if k in info and info[k] is not None:
            out[k] = info[k]
    return out


def _resolve_output_path(work_dir: Path, info: dict[str, Any]) -> Path | None:
    fp = info.get("filepath")
    if fp:
        path = Path(fp)
        if path.is_file():
            return path.resolve()
    req = info.get("requested_downloads")
    if isinstance(req, list) and req:
        last = req[-1]
        if isinstance(last, dict):
            fp2 = last.get("filepath")
            if fp2:
                p2 = Path(fp2)
                if p2.is_file():
                    return p2.resolve()
    pattern = info.get("id")
    if pattern:
        escaped = re.escape(str(pattern))
        for p in sorted(
            work_dir.glob(f"{escaped}*"),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        ):
            if p.is_file() and not p.name.endswith(".part"):
                return p.resolve()
    candidates = sorted(
        (p for p in work_dir.iterdir() if p.is_file() and not p.name.endswith(".part")),
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    )
    if len(candidates) == 1:
        return candidates[0].resolve()
    return None


def cleanup_work_dir(work_dir: Path, *, strict: bool = True) -> None:
    root = work_dir.resolve()
    if strict:
        tmp = Path(tempfile.gettempdir()).resolve()
        try:
            root.relative_to(tmp)
        except ValueError as exc:
            raise ValueError(
                f"Refusing to delete outside temp dir ({tmp}): {root}"
            ) from exc
    if root.is_dir():
        shutil.rmtree(root, ignore_errors=False)
    elif root.exists():
        root.unlink()


def extract_info_only(
    url: str,
    *,
    work_dir: Path,
    config_path: Path | None = None,
) -> dict[str, Any]:
    _validate_http_url(url)
    base = work_dir.resolve()
    base.mkdir(parents=True, exist_ok=True)
    opts = _build_common_ydl_opts(base, config_path=config_path)
    opts["skip_download"] = True
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url.strip(), download=False)
    except YtDlpDownloadErrorRaw as exc:
        _raise_mapped_download_error(url.strip(), exc)
    assert isinstance(info, dict)
    return info


def download_video_sync(
    url: str,
    *,
    work_dir: Path,
    config_path: Path | None = None,
    progress_hook: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[Path, dict[str, Any]]:
    _validate_http_url(url)
    base = work_dir.resolve()
    base.mkdir(parents=True, exist_ok=True)
    opts = _build_common_ydl_opts(base, config_path=config_path)
    if progress_hook is not None:
        opts["progress_hooks"] = [progress_hook]
    opts.update(
        {
            "format": "bestvideo*+bestaudio/best",
            "merge_output_format": "mp4",
        }
    )
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url.strip(), download=True)
    except YtDlpDownloadErrorRaw as exc:
        _raise_mapped_download_error(url.strip(), exc)

    assert isinstance(info, dict)
    outfile = _resolve_output_path(base, info)
    if outfile is None or not outfile.is_file():
        raise YtDlpDownloadError(
            "Download finished but output file could not be located",
            url=url.strip(),
        )
    return outfile, slim_metadata(info)


def download_audio_sync(
    url: str,
    *,
    work_dir: Path,
    config_path: Path | None = None,
    progress_hook: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[Path, dict[str, Any]]:
    _validate_http_url(url)
    base = work_dir.resolve()
    base.mkdir(parents=True, exist_ok=True)
    opts = _build_common_ydl_opts(base, config_path=config_path)
    if progress_hook is not None:
        opts["progress_hooks"] = [progress_hook]
    opts.update(
        {
            "format": "bestaudio/best",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
            "outtmpl": str(base / "%(id)s_%(title).100B.%(ext)s"),
        }
    )
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url.strip(), download=True)
    except YtDlpDownloadErrorRaw as exc:
        _raise_mapped_download_error(url.strip(), exc)

    assert isinstance(info, dict)
    outfile = _resolve_output_path(base, info)
    if outfile is None:
        mp3s = [p for p in base.glob("*.mp3") if p.is_file()]
        if len(mp3s) == 1:
            outfile = mp3s[0].resolve()
    if outfile is None or not outfile.is_file() or outfile.suffix.lower() != ".mp3":
        raise YtDlpDownloadError(
            "Audio download finished but MP3 output was not found (is ffmpeg installed?)",
            url=url.strip(),
        )
    return outfile, slim_metadata(info)
