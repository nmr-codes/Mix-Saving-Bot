from __future__ import annotations

import asyncio
import contextlib
import shutil
import time
from typing import Protocol

from core.contracts.errors import DownloaderFatalError, DownloaderTransientError, SanitizeError
from core.contracts.types import JobOutputRef, JobRecord, QueueMessage
from core.logging_setup import get_logger
from core.observability import get_metrics
from core.settings import Settings
from downloader.protocols import DownloadConstraints, DownloadJobContext, MediaDownloader
from downloader.sanitize import canonical_cache_key, validate_for_download
from downloader.yt_dlp_downloader import temp_work_dir

from services.cache.protocols import CacheStore
from services.jobs.service import JobServiceImpl
from services.queue.protocols import QueueConsumer

log = get_logger("services.worker_runner")


class Notifier(Protocol):
    async def notify_job_update(self, job: JobRecord) -> None:
        ...


async def run_worker_loop(
    consumer: QueueConsumer,
    jobs: JobServiceImpl,
    cache: CacheStore,
    downloader: MediaDownloader,
    notifier: Notifier,
    settings: Settings,
    *,
    stop_event: asyncio.Event | None = None,
) -> None:
    sem = asyncio.Semaphore(max(1, settings.MAX_CONCURRENT_DOWNLOADS))
    metrics = get_metrics()

    async def handle(msg: QueueMessage) -> None:
        job_id = msg["job_id"]
        rec = await jobs.get(job_id)
        if rec is None:
            log.warning("unknown job id", extra={"job_id": job_id})
            return
        if rec["status"] in ("succeeded", "failed", "canceled"):
            return

        req = rec["request"]
        constraints = DownloadConstraints(
            max_duration_sec=settings.MAX_DURATION_SEC,
            max_file_size_bytes=settings.MAX_OUTPUT_BYTES,
            allowed_hosts=settings.ALLOWED_HOSTS,
        )
        try:
            validate_for_download(req["source_url"], constraints)
        except SanitizeError as exc:
            await jobs.mark_failed(job_id, "UNSUPPORTED", str(exc))
            row = await jobs.get(job_id)
            if row:
                await notifier.notify_job_update(row)
            return

        # Blob cache is global per URL+format; job dedupe_key may be chat-scoped.
        cache_key = canonical_cache_key(
            req["source_url"],
            req.get("requested_format_id"),
        )
        chat = req["chat"]
        log.info(
            "download job received",
            extra={
                "job_id": job_id,
                "correlation_id": msg["correlation_id"],
                "source_url": req["source_url"],
                "requested_format_id": req.get("requested_format_id"),
                "chat_id": chat["chat_id"],
                "user_id": chat["user_id"],
                "cache_key": cache_key,
            },
        )

        cached = await cache.get(cache_key)
        if cached is not None:
            log.info(
                "download cache hit, skipping fetch",
                extra={
                    "job_id": job_id,
                    "cache_key": cache_key,
                    "local_path": cached["local_path"],
                    "byte_size": cached["byte_size"],
                },
            )
            await jobs.mark_running(job_id)
            out: JobOutputRef = {
                "kind": "local_path",
                "value": cached["local_path"],
                "byte_size": cached["byte_size"],
            }
            await jobs.mark_succeeded(job_id, [out])
            row = await jobs.get(job_id)
            if row:
                await notifier.notify_job_update(row)
            await metrics.inc("cache_hit_total")
            await metrics.inc("jobs_completed_total")
            return

        await metrics.inc("cache_miss_total")
        log.info(
            "download cache miss, fetching",
            extra={"job_id": job_id, "cache_key": cache_key},
        )
        await jobs.mark_running(job_id)

        work_dir = temp_work_dir(job_id)
        t0 = time.monotonic()
        try:

            async def on_progress(p: object) -> None:
                if not isinstance(p, dict):
                    return
                stage = p.get("stage")
                pct = p.get("pct")
                msg = p.get("message")
                parts = [f"stage={stage}"]
                if isinstance(msg, str) and msg:
                    parts.append(msg)
                if pct is not None:
                    parts.append(f"pct={pct}")
                log.info(
                    "download pipeline | " + " | ".join(parts),
                    extra={
                        "job_id": job_id,
                        "source_url": req["source_url"],
                        "stage": stage,
                        "pipeline_message": msg,
                        "pct": pct,
                    },
                )
                log.debug(
                    "download pipeline detail",
                    extra={"job_id": job_id, "detail": p},
                )

            async with sem:
                ctx = DownloadJobContext(
                    job_id=job_id,
                    source_url=req["source_url"],
                    constraints=constraints,
                    requested_format_id=req.get("requested_format_id"),
                    work_dir=str(work_dir),
                )

                items: list[dict[str, object]] | None = None
                transient_attempted = False
                while True:
                    try:
                        items = await asyncio.wait_for(
                            downloader.download(ctx, on_progress),
                            timeout=settings.DOWNLOAD_DEADLINE_SEC,
                        )
                        break
                    except TimeoutError:
                        await jobs.mark_failed(
                            job_id,
                            "TIMEOUT",
                            "Download took too long. Try again later.",
                        )
                        row = await jobs.get(job_id)
                        if row:
                            await notifier.notify_job_update(row)
                        return
                    except DownloaderTransientError:
                        if not transient_attempted:
                            transient_attempted = True
                            await asyncio.sleep(1.0)
                            continue
                        await jobs.mark_failed(
                            job_id,
                            "DOWNLOADER_ERROR",
                            "Temporary error while downloading. Try again.",
                        )
                        row = await jobs.get(job_id)
                        if row:
                            await notifier.notify_job_update(row)
                        return
                    except DownloaderFatalError as exc:
                        await jobs.mark_failed(job_id, "UNSUPPORTED", str(exc))
                        row = await jobs.get(job_id)
                        if row:
                            await notifier.notify_job_update(row)
                        return

            assert items is not None and len(items) > 0
            primary = items[0]
            local_path = str(primary["local_path"])
            log.info(
                "download fetched, caching",
                extra={
                    "job_id": job_id,
                    "local_path": local_path,
                    "title": primary.get("title"),
                    "duration_sec": primary.get("duration_sec"),
                    "mime_type": primary.get("mime_type"),
                },
            )
            entry = await cache.put_from_path(cache_key, local_path)
            mime_raw = primary.get("mime_type")
            mime_type: str | None = mime_raw if isinstance(mime_raw, str) else None
            outputs: list[JobOutputRef] = [
                {
                    "kind": "local_path",
                    "value": entry["local_path"],
                    "byte_size": entry["byte_size"],
                }
            ]
            if mime_type:
                outputs[0]["mime_type"] = mime_type
            await jobs.mark_succeeded(job_id, outputs)
            row = await jobs.get(job_id)
            if row:
                await notifier.notify_job_update(row)
            await metrics.inc("jobs_completed_total")
            log.info(
                "download job succeeded",
                extra={
                    "job_id": job_id,
                    "seconds": round(time.monotonic() - t0, 3),
                    "output_byte_size": entry["byte_size"],
                    "cached_path": entry["local_path"],
                },
            )
        finally:
            dt = time.monotonic() - t0
            await metrics.observe_duration_sec("download_duration_seconds", dt)
            shutil.rmtree(work_dir, ignore_errors=True)

    async def wrapped(msg: QueueMessage) -> None:
        try:
            await handle(msg)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("worker handle failed", extra={"job_id": msg["job_id"]})
            await jobs.mark_failed(
                msg["job_id"],
                "INTERNAL",
                "An internal error occurred.",
            )
            row = await jobs.get(msg["job_id"])
            if row:
                await notifier.notify_job_update(row)

    async def consume_forever() -> None:
        await consumer.subscribe(wrapped)

    if stop_event is None:
        await consume_forever()
    else:
        task = asyncio.create_task(consume_forever(), name="queue-consumer")
        try:
            await stop_event.wait()
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
