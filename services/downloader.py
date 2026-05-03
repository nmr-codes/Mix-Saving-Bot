"""
yt-dlp-based media download engine (YouTube, Instagram, TikTok).

Synchronous API for use from async backends via ``asyncio.to_thread``.
Callers own ``DownloadResult.work_dir`` unless they passed a custom path; use
``cleanup_work_dir`` when files are no longer needed.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError as YtDlpDownloadErrorRaw


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_ytdlp_config_path() -> Path:
    """
    Resolved config path: ``MIX_SAVING_YTDLP_CONFIG`` if set, else bundled
    ``services/yt-dlp.conf``, else repo ``config/yt-dlp.conf`` for editable checkouts.
    """
    env = os.environ.get("MIX_SAVING_YTDLP_CONFIG")
    if env:
        return Path(env).expanduser().resolve()
    bundled = Path(__file__).resolve().parent / "yt-dlp.conf"
    if bundled.is_file():
        return bundled
    return _project_root() / "config" / "yt-dlp.conf"


@dataclass(frozen=True)
class DownloadResult:
    """Paths and metadata after a successful download."""

    path: Path
    work_dir: Path
    metadata: dict[str, Any] = field(default_factory=dict)


class YtDlpDownloadError(Exception):
    """Raised when yt-dlp cannot complete a download."""

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
    """Malformed URL or no supported extractor."""


class PrivateContentError(YtDlpDownloadError):
    """Sign-in required, private/restricted, or deleted content."""


class GeoBlockedError(YtDlpDownloadError):
    """Content not available in this region."""


def _validate_http_url(url: str) -> None:
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
    # Prefer region locks before generic "unavailable" heuristics.
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


def _raise_mapped_download_error(
    url: str, exc: YtDlpDownloadErrorRaw
) -> None:
    msg = str(exc) or getattr(exc, "msg", "") or repr(exc)
    category = _classify_message(msg)
    if category is not None:
        raise category(msg, url=url, original=exc) from exc
    raise YtDlpDownloadError(msg, url=url, original=exc) from exc


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


def _slim_metadata(info: dict[str, Any]) -> dict[str, Any]:
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
        for p in sorted(work_dir.glob(f"{re.escape(str(pattern))}*"), key=lambda x: x.stat().st_mtime, reverse=True):
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
    """
    Remove a temporary download directory created for a single job.

    If ``strict`` is True, only paths under the system temp directory are removed.
    """
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


def download_video(
    url: str,
    *,
    work_dir: Path | None = None,
    config_path: Path | None = None,
) -> DownloadResult:
    """
    Download best available video (merged to MP4 when ffmpeg is available).

    Auto-detects platform via yt-dlp. Output lives under ``work_dir``; if
    ``work_dir`` is omitted, a new directory under ``tempfile.gettempdir()``
    is created and returned on success (caller must ``cleanup_work_dir``).
    """
    _validate_http_url(url)
    owns_dir = work_dir is None
    base = Path(work_dir) if work_dir is not None else Path(tempfile.mkdtemp(prefix="mix-saving-v-"))
    base = base.resolve()
    base.mkdir(parents=True, exist_ok=True)

    opts = _build_common_ydl_opts(base, config_path=config_path)
    opts.update(
        {
            "format": "bestvideo*+bestaudio/best",
            "merge_output_format": "mp4",
        }
    )

    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except YtDlpDownloadErrorRaw as exc:
        if owns_dir:
            shutil.rmtree(base, ignore_errors=True)
        _raise_mapped_download_error(url.strip(), exc)
    except Exception:
        if owns_dir:
            shutil.rmtree(base, ignore_errors=True)
        raise

    assert isinstance(info, dict)
    outfile = _resolve_output_path(base, info)
    if outfile is None or not outfile.is_file():
        if owns_dir:
            shutil.rmtree(base, ignore_errors=True)
        raise YtDlpDownloadError(
            "Download finished but output file could not be located",
            url=url.strip(),
        )

    return DownloadResult(
        path=outfile,
        work_dir=base,
        metadata=_slim_metadata(info),
    )


def download_audio(
    url: str,
    *,
    work_dir: Path | None = None,
    config_path: Path | None = None,
) -> DownloadResult:
    """
    Download audio and extract to MP3 (requires ffmpeg on PATH or MIX_SAVING_FFMPEG_LOCATION).
    """
    _validate_http_url(url)
    owns_dir = work_dir is None
    base = Path(work_dir) if work_dir is not None else Path(tempfile.mkdtemp(prefix="mix-saving-a-"))
    base = base.resolve()
    base.mkdir(parents=True, exist_ok=True)

    opts = _build_common_ydl_opts(base, config_path=config_path)
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
            # Postprocessor replaces extension with .mp3
            "outtmpl": str(base / "%(id)s_%(title).100B.%(ext)s"),
        }
    )

    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except YtDlpDownloadErrorRaw as exc:
        if owns_dir:
            shutil.rmtree(base, ignore_errors=True)
        _raise_mapped_download_error(url.strip(), exc)
    except Exception:
        if owns_dir:
            shutil.rmtree(base, ignore_errors=True)
        raise

    assert isinstance(info, dict)
    # After FFmpegExtractAudio, expected path is sibling .mp3
    outfile = _resolve_output_path(base, info)
    if outfile is None:
        mp3s = list(base.glob("*.mp3"))
        mp3s = [p for p in mp3s if p.is_file()]
        if len(mp3s) == 1:
            outfile = mp3s[0].resolve()

    if outfile is None or not outfile.is_file() or outfile.suffix.lower() != ".mp3":
        if owns_dir:
            shutil.rmtree(base, ignore_errors=True)
        raise YtDlpDownloadError(
            "Audio download finished but MP3 output was not found (is ffmpeg installed?)",
            url=url.strip(),
        )

    return DownloadResult(
        path=outfile,
        work_dir=base,
        metadata=_slim_metadata(info),
    )


__all__ = [
    "DownloadResult",
    "GeoBlockedError",
    "InvalidURLError",
    "PrivateContentError",
    "YtDlpDownloadError",
    "cleanup_work_dir",
    "default_ytdlp_config_path",
    "download_audio",
    "download_video",
]
