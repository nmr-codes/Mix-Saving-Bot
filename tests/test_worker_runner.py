from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from core.contracts.errors import DownloaderFatalError, DownloaderTransientError
from core.contracts.types import JobOutputRef, QueueMessage, SubmitDownloadRequest
from core.settings import Settings
from downloader.protocols import DownloadJobContext

from services.cache.file_cache import FileCacheStore
from services.jobs.model import make_job_record, new_job_id
from services.jobs.repository import InMemoryJobRepository
from services.jobs.service import JobServiceImpl
from services.worker_runner import run_worker_loop

_real_asyncio_sleep = asyncio.sleep


@pytest.fixture(autouse=True)
def _instant_worker_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Collapse worker backoff sleep without breaking other asyncio.Sleep users."""

    async def shim(delay: float = 0, *args: object, **kwargs: object) -> None:
        await _real_asyncio_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", shim)


def _youtube_req(**kwargs: Any) -> SubmitDownloadRequest:
    chat_id = int(kwargs.get("chat_id", 1))
    user_id = int(kwargs.get("user_id", 2))
    base: SubmitDownloadRequest = {
        "source_url": str(
            kwargs.get("source_url", "https://www.youtube.com/watch?v=testid"),
        ),
        "correlation_id": str(kwargs.get("correlation_id", "corr-1")),
        "chat": {"chat_id": chat_id, "user_id": user_id},
    }
    if "requested_format_id" in kwargs:
        base["requested_format_id"] = str(kwargs["requested_format_id"])
    return base


def _qm(job_id: str) -> QueueMessage:
    return {
        "job_id": job_id,
        "correlation_id": "cm-1",
        "enqueued_at_unix": 0.0,
    }


class HangSubscribeConsumer:
    """Delivers queued messages sequentially, then blocks until cancelled."""

    def __init__(self, messages: list[QueueMessage]) -> None:
        self._messages = messages
        self.handlers_done = asyncio.Event()

    async def subscribe(self, handler):  # type: ignore[no-untyped-def]
        try:
            for m in self._messages:
                await handler(m)
            self.handlers_done.set()
            await asyncio.Future()
        except asyncio.CancelledError:
            raise


class RecordingNotifier:
    def __init__(self) -> None:
        self.updates: list[Any] = []

    async def notify_job_update(self, job) -> None:  # type: ignore[no-untyped-def]
        self.updates.append(job)


class OkDownloader:
    async def probe(self, ctx: DownloadJobContext) -> dict[str, Any]:
        return {}

    async def download(self, ctx: DownloadJobContext, on_progress) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
        path = Path(ctx.work_dir) / "out.mp4"
        path.write_bytes(b"bytes")
        await on_progress({"stage": "starting", "message": "starting"})
        return [
            {
                "local_path": str(path),
                "title": "ttl",
                "duration_sec": 10,
                "mime_type": "video/mp4",
            }
        ]


@pytest.mark.asyncio
async def test_worker_unknown_job_does_not_crash(tmp_path: Path) -> None:
    repo = InMemoryJobRepository()
    jobs = JobServiceImpl(repo)
    cache = FileCacheStore(tmp_path / "cache")
    notifier = RecordingNotifier()
    settings = Settings()
    consumer = HangSubscribeConsumer([_qm("missing-id")])

    stop = asyncio.Event()
    task = asyncio.create_task(
        run_worker_loop(
            consumer,
            jobs,
            cache,
            OkDownloader(),
            notifier,
            settings,
            stop_event=stop,
        )
    )
    await asyncio.wait_for(consumer.handlers_done.wait(), timeout=2.0)
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)
    assert notifier.updates == []


@pytest.mark.asyncio
async def test_worker_skips_terminal_job(tmp_path: Path) -> None:
    repo = InMemoryJobRepository()
    jid = new_job_id()
    rec = make_job_record(jid, "succeeded", _youtube_req())
    rec["outputs"] = [
        JobOutputRef(kind="local_path", value="/x", byte_size=1),
    ]
    await repo.save(rec)
    jobs = JobServiceImpl(repo)
    cache = FileCacheStore(tmp_path / "cache")
    notifier = RecordingNotifier()
    settings = Settings()
    consumer = HangSubscribeConsumer([_qm(jid)])

    stop = asyncio.Event()
    task = asyncio.create_task(
        run_worker_loop(
            consumer,
            jobs,
            cache,
            OkDownloader(),
            notifier,
            settings,
            stop_event=stop,
        )
    )
    await asyncio.wait_for(consumer.handlers_done.wait(), timeout=2.0)
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)
    assert notifier.updates == []


@pytest.mark.asyncio
async def test_worker_sanitize_failure_marks_unsupported(tmp_path: Path) -> None:
    repo = InMemoryJobRepository()
    jid = new_job_id()
    bad_req = _youtube_req(source_url="ftp://example.com/x")
    await repo.save(make_job_record(jid, "queued", bad_req))
    jobs = JobServiceImpl(repo)
    cache = FileCacheStore(tmp_path / "cache")
    notifier = RecordingNotifier()
    settings = Settings()
    consumer = HangSubscribeConsumer([_qm(jid)])

    stop = asyncio.Event()
    task = asyncio.create_task(
        run_worker_loop(
            consumer,
            jobs,
            cache,
            OkDownloader(),
            notifier,
            settings,
            stop_event=stop,
        )
    )
    await asyncio.wait_for(consumer.handlers_done.wait(), timeout=2.0)
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)

    row = await jobs.get(jid)
    assert row is not None
    assert row["status"] == "failed"
    assert row.get("error_code") == "UNSUPPORTED"
    assert len(notifier.updates) == 1


@pytest.mark.asyncio
async def test_worker_cache_hit_short_circuits(tmp_path: Path) -> None:
    blob = tmp_path / "blob.mp4"
    blob.write_bytes(b"cached")
    cache = FileCacheStore(tmp_path / "cache_root")
    from downloader.sanitize import canonical_cache_key

    key = canonical_cache_key("https://www.youtube.com/watch?v=testid", "video")
    await cache.put_from_path(key, str(blob))

    repo = InMemoryJobRepository()
    jid = new_job_id()
    await repo.save(
        make_job_record(
            jid,
            "queued",
            _youtube_req(requested_format_id="video"),
        )
    )
    jobs = JobServiceImpl(repo)
    notifier = RecordingNotifier()
    settings = Settings()
    consumer = HangSubscribeConsumer([_qm(jid)])

    stop = asyncio.Event()
    task = asyncio.create_task(
        run_worker_loop(
            consumer,
            jobs,
            cache,
            OkDownloader(),
            notifier,
            settings,
            stop_event=stop,
        )
    )
    await asyncio.wait_for(consumer.handlers_done.wait(), timeout=2.0)
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)

    row = await jobs.get(jid)
    assert row is not None
    assert row["status"] == "succeeded"
    outs = row.get("outputs") or []
    assert outs and outs[0]["byte_size"] == len(b"cached")


@pytest.mark.asyncio
async def test_worker_download_and_cache_miss(tmp_path: Path) -> None:
    repo = InMemoryJobRepository()
    jid = new_job_id()
    await repo.save(make_job_record(jid, "queued", _youtube_req(requested_format_id="video")))
    jobs = JobServiceImpl(repo)
    cache = FileCacheStore(tmp_path / "cache_root")
    notifier = RecordingNotifier()
    settings = Settings()
    consumer = HangSubscribeConsumer([_qm(jid)])

    stop = asyncio.Event()
    task = asyncio.create_task(
        run_worker_loop(
            consumer,
            jobs,
            cache,
            OkDownloader(),
            notifier,
            settings,
            stop_event=stop,
        )
    )
    await asyncio.wait_for(consumer.handlers_done.wait(), timeout=2.0)
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)

    row = await jobs.get(jid)
    assert row is not None
    assert row["status"] == "succeeded"
    key = row["request"]["source_url"]
    assert key.startswith("https://")


@pytest.mark.asyncio
async def test_worker_timeout(tmp_path: Path) -> None:
    class SlowDownloader(OkDownloader):
        async def download(self, ctx, on_progress) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def,override]
            await asyncio.Event().wait()
            return await super().download(ctx, on_progress)

    repo = InMemoryJobRepository()
    jid = new_job_id()
    await repo.save(make_job_record(jid, "queued", _youtube_req()))
    jobs = JobServiceImpl(repo)
    cache = FileCacheStore(tmp_path / "cache_root")
    notifier = RecordingNotifier()
    settings = Settings(DOWNLOAD_DEADLINE_SEC=1)
    consumer = HangSubscribeConsumer([_qm(jid)])

    stop = asyncio.Event()
    task = asyncio.create_task(
        run_worker_loop(
            consumer,
            jobs,
            cache,
            SlowDownloader(),
            notifier,
            settings,
            stop_event=stop,
        )
    )
    await asyncio.wait_for(consumer.handlers_done.wait(), timeout=5.0)
    stop.set()
    await asyncio.wait_for(task, timeout=5.0)

    row = await jobs.get(jid)
    assert row is not None
    assert row["status"] == "failed"
    assert row.get("error_code") == "TIMEOUT"


@pytest.mark.asyncio
async def test_worker_transient_retry_then_fail(tmp_path: Path) -> None:
    class FlakyDownloader(OkDownloader):
        def __init__(self) -> None:
            self.calls = 0

        async def download(self, ctx, on_progress) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def,override]
            self.calls += 1
            if self.calls == 1:
                raise DownloaderTransientError("retry me")
            if self.calls == 2:
                raise DownloaderTransientError("still bad")
            return await super().download(ctx, on_progress)

    repo = InMemoryJobRepository()
    jid = new_job_id()
    await repo.save(make_job_record(jid, "queued", _youtube_req()))
    jobs = JobServiceImpl(repo)
    cache = FileCacheStore(tmp_path / "cache_root")
    notifier = RecordingNotifier()
    settings = Settings()
    consumer = HangSubscribeConsumer([_qm(jid)])

    stop = asyncio.Event()
    task = asyncio.create_task(
        run_worker_loop(
            consumer,
            jobs,
            cache,
            FlakyDownloader(),
            notifier,
            settings,
            stop_event=stop,
        )
    )
    await asyncio.wait_for(consumer.handlers_done.wait(), timeout=5.0)
    stop.set()
    await asyncio.wait_for(task, timeout=5.0)

    row = await jobs.get(jid)
    assert row is not None
    assert row["status"] == "failed"
    assert row.get("error_code") == "DOWNLOADER_ERROR"


@pytest.mark.asyncio
async def test_worker_fatal_downloader_error(tmp_path: Path) -> None:
    class BadDownloader(OkDownloader):
        async def download(self, ctx, on_progress) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def,override]
            raise DownloaderFatalError("too big")

    repo = InMemoryJobRepository()
    jid = new_job_id()
    await repo.save(make_job_record(jid, "queued", _youtube_req()))
    jobs = JobServiceImpl(repo)
    cache = FileCacheStore(tmp_path / "cache_root")
    notifier = RecordingNotifier()
    settings = Settings()
    consumer = HangSubscribeConsumer([_qm(jid)])

    stop = asyncio.Event()
    task = asyncio.create_task(
        run_worker_loop(
            consumer,
            jobs,
            cache,
            BadDownloader(),
            notifier,
            settings,
            stop_event=stop,
        )
    )
    await asyncio.wait_for(consumer.handlers_done.wait(), timeout=5.0)
    stop.set()
    await asyncio.wait_for(task, timeout=5.0)

    row = await jobs.get(jid)
    assert row is not None
    assert row["status"] == "failed"
    assert row.get("error_code") == "UNSUPPORTED"


@pytest.mark.asyncio
async def test_worker_internal_error_wraps(tmp_path: Path) -> None:
    class BoomDownloader(OkDownloader):
        async def download(self, ctx, on_progress) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def,override]
            raise RuntimeError("boom")

    repo = InMemoryJobRepository()
    jid = new_job_id()
    await repo.save(make_job_record(jid, "queued", _youtube_req()))
    jobs = JobServiceImpl(repo)
    cache = FileCacheStore(tmp_path / "cache_root")
    notifier = RecordingNotifier()
    settings = Settings()
    consumer = HangSubscribeConsumer([_qm(jid)])

    stop = asyncio.Event()
    task = asyncio.create_task(
        run_worker_loop(
            consumer,
            jobs,
            cache,
            BoomDownloader(),
            notifier,
            settings,
            stop_event=stop,
        )
    )
    await asyncio.wait_for(consumer.handlers_done.wait(), timeout=5.0)
    stop.set()
    await asyncio.wait_for(task, timeout=5.0)

    row = await jobs.get(jid)
    assert row is not None
    assert row["status"] == "failed"
    assert row.get("error_code") == "INTERNAL"
    assert len(notifier.updates) >= 1
