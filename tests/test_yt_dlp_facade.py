from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from core.settings import Settings
from downloader.protocols import DownloadConstraints, DownloadJobContext

import downloader.yt_dlp_downloader as ymod


@pytest.fixture
def patched_settings(tmp_path: Path) -> Settings:
    conf = tmp_path / "yt-dlp.conf"
    conf.write_text("# stub\n")
    return Settings(YTDLP_CONFIG_PATH=conf)


@pytest.mark.asyncio
async def test_download_wires_progress_hook_for_video(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, patched_settings: Settings
) -> None:
    calls: list[Any] = []

    def fake_video(
        url: str,
        *,
        work_dir: Path,
        config_path: Path | None = None,
        progress_hook=None,  # noqa: ANN001
    ) -> tuple[Path, dict[str, Any]]:
        if progress_hook:
            progress_hook({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 2})
        calls.append(progress_hook)
        p = Path(work_dir) / "f.mp4"
        p.write_bytes(b"x")
        return p, {}

    monkeypatch.setattr(ymod.sync, "download_video_sync", fake_video)

    defaults = Settings()
    constraints = DownloadConstraints(
        max_duration_sec=defaults.MAX_DURATION_SEC,
        max_file_size_bytes=defaults.MAX_OUTPUT_BYTES,
        allowed_hosts=defaults.ALLOWED_HOSTS,
    )
    ctx = DownloadJobContext(
        job_id="j1",
        source_url="https://youtube.com/watch?v=1",
        constraints=constraints,
        requested_format_id="video",
        work_dir=str(tmp_path / "w"),
    )

    dl = ymod.YtDlpMediaDownloader(patched_settings)

    async def on_progress(_):
        return None

    out = await dl.download(ctx, on_progress)
    assert out[0]["local_path"].endswith("f.mp4")
    assert calls and calls[0] is not None


@pytest.mark.asyncio
async def test_download_uses_audio_branch_for_audio_format(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, patched_settings: Settings
) -> None:
    used: list[str] = []

    def fake_audio(
        url: str,
        *,
        work_dir: Path,
        config_path: Path | None = None,
        progress_hook=None,  # noqa: ANN001
    ) -> tuple[Path, dict[str, Any]]:
        used.append("audio")
        p = Path(work_dir) / "a.mp3"
        p.write_bytes(b"x")
        return p, {}

    def fake_video(*_a, **_k):  # noqa: ANN002, ANN003
        raise AssertionError("video should not be used")

    monkeypatch.setattr(ymod.sync, "download_audio_sync", fake_audio)
    monkeypatch.setattr(ymod.sync, "download_video_sync", fake_video)

    defaults = Settings()
    constraints = DownloadConstraints(
        defaults.MAX_DURATION_SEC,
        defaults.MAX_OUTPUT_BYTES,
        defaults.ALLOWED_HOSTS,
    )
    ctx = DownloadJobContext(
        job_id="j",
        source_url="https://youtube.com/x",
        constraints=constraints,
        requested_format_id="audio",
        work_dir=str(tmp_path / "wa"),
    )

    dl = ymod.YtDlpMediaDownloader(patched_settings)

    async def nop(_):
        return None

    out = await dl.download(ctx, nop)
    assert used == ["audio"]
    assert out[0]["mime_type"] == "audio/mpeg"


def test_temp_work_dir_is_under_system_temp() -> None:
    p = ymod.temp_work_dir("abc")
    assert p.is_dir()
    p.rmdir()
