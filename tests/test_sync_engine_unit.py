"""Unit tests for downloader._sync_engine helpers (no network / yt-dlp runs)."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest import mock

import pytest
from yt_dlp.utils import DownloadError as YtDlpDownloadErrorRaw

from downloader import _sync_engine as se


def test_project_root_contains_downloader_package() -> None:
    root = se.project_root()
    assert (root / "downloader" / "_sync_engine.py").is_file()


def test_default_ytdlp_config_path_explicit() -> None:
    p = Path("/tmp/fake-ytdlp.conf")
    assert se.default_ytdlp_config_path(p) == p


def test_default_ytdlp_config_path_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = tmp_path / "env.conf"
    cfg.write_text("{}")
    monkeypatch.setenv("MIX_SAVING_YTDLP_CONFIG", str(cfg))
    assert se.default_ytdlp_config_path(None).resolve() == cfg.resolve()


def test_default_ytdlp_config_path_uses_bundled_when_no_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MIX_SAVING_YTDLP_CONFIG", raising=False)
    got = se.default_ytdlp_config_path(None)
    assert got.resolve() == (Path(se.__file__).resolve().parent / "yt-dlp.conf")
    assert got.is_file()


@pytest.mark.parametrize(
    ("url", "exc_type"),
    [
        ("", se.InvalidURLError),
        ("   ", se.InvalidURLError),
        ("ftp://x", se.InvalidURLError),
        ("https://", se.InvalidURLError),
    ],
)
def test_validate_http_url_rejects(url: str, exc_type: type[Exception]) -> None:
    with pytest.raises(exc_type):
        se._validate_http_url(url)


def test_validate_http_url_accepts_trimmed() -> None:
    se._validate_http_url("  https://example.com/x  ")


def test_pct_from_progress_dict() -> None:
    assert se._pct_from_progress_dict({}) is None
    assert se._pct_from_progress_dict({"total_bytes": 0, "downloaded_bytes": 0}) is None
    assert se._pct_from_progress_dict({"total_bytes": 100, "downloaded_bytes": 25}) == 25.0
    assert (
        se._pct_from_progress_dict({"total_bytes_estimate": 10, "downloaded_bytes": 3}) == 30.0
    )


def test_classify_message_geo() -> None:
    assert se._classify_message("Not available in your country") is se.GeoBlockedError


def test_classify_message_private() -> None:
    assert se._classify_message("This is a private video") is se.PrivateContentError


def test_classify_message_invalid() -> None:
    assert se._classify_message("Unsupported URL") is se.InvalidURLError


def test_classify_message_unknown() -> None:
    assert se._classify_message("some random failure") is None


def test_raise_mapped_download_error_categories() -> None:
    with pytest.raises(se.GeoBlockedError):
        se._raise_mapped_download_error("http://u", YtDlpDownloadErrorRaw("geo-restricted"))

    with pytest.raises(se.PrivateContentError):
        se._raise_mapped_download_error("http://u", YtDlpDownloadErrorRaw("login required"))

    with pytest.raises(se.InvalidURLError):
        se._raise_mapped_download_error("http://u", YtDlpDownloadErrorRaw("unsupported url"))

    with pytest.raises(se.YtDlpDownloadError):
        se._raise_mapped_download_error("http://u", YtDlpDownloadErrorRaw("unexpected blob"))


def test_ytdlp_download_error_attrs() -> None:
    inner = ValueError("inner")
    exc = se.YtDlpDownloadError("m", url="http://z", original=inner)
    assert exc.url == "http://z"
    assert exc.original is inner


def test_build_progress_hook_log_full_every(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="downloader.ytdlp")
    hook = se.build_ytdlp_progress_hook(
        "jid-1",
        "https://youtube.com/x",
        log_full_every_hook=True,
    )
    hook({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 10})
    hook({"status": "finished"})
    infos = [r for r in caplog.records if r.name == "downloader.ytdlp" and r.levelno == logging.INFO]
    assert len(infos) >= 2


def test_build_progress_hook_throttles_info(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="downloader.ytdlp")
    hook = se.build_ytdlp_progress_hook(
        "jid",
        "https://youtube.com/x",
        log_full_every_hook=False,
    )

    vals = iter([100.0, 100.0, 112.0, 112.0])

    def fake_mono() -> float:
        return next(vals)

    with mock.patch("downloader._sync_engine.time.monotonic", side_effect=fake_mono):
        hook({"status": "downloading", "downloaded_bytes": 10, "total_bytes": 100})
        hook({"status": "downloading", "downloaded_bytes": 95, "total_bytes": 100})

    debugs = [
        r for r in caplog.records if r.name == "downloader.ytdlp" and r.levelno == logging.DEBUG
    ]
    infos = [
        r for r in caplog.records if r.name == "downloader.ytdlp" and r.levelno == logging.INFO
    ]
    assert len(debugs) >= 1
    assert len(infos) >= 1


def test_build_progress_hook_non_downloading_emits_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="downloader.ytdlp")
    hook = se.build_ytdlp_progress_hook(None, "https://x", log_full_every_hook=False)
    hook({"status": "finished", "filename": "x.mp4"})
    assert any(
        r.levelno == logging.INFO and "yt-dlp progress" in r.getMessage()
        for r in caplog.records
        if r.name == "downloader.ytdlp"
    )
