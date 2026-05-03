from __future__ import annotations

import asyncio
import json
import os
import pathlib
import tempfile
import time
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit, urlunsplit

import aiohttp

from services.dedupe_cache import DownloadCache
from services.logging_config import get_logger
from services.types import Job, JobStatus, TaskResult

log = get_logger("services.remote_backend")

_DEFAULT_JOB_PATH = "/api/v1/jobs"
_DEFAULT_POLL_INTERVAL = float(os.getenv("MIX_BACKEND_POLL_INTERVAL", "1.25"))
_DEFAULT_MAX_WAIT = float(os.getenv("MIX_BACKEND_JOB_TIMEOUT_SEC", "900"))

_API_BASE_ERROR = TaskResult(
    job_id="__invalid__",
    status=JobStatus.FAILED,
    message="Downloader API is not configured.",
    detail={"error_code": "BACKEND_NOT_CONFIGURED"},
)


def _normalize_api_base(raw: str) -> str:
    parts = urlsplit(raw.strip())
    if not parts.scheme or not parts.netloc:
        return ""
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def api_base_env() -> str:
    raw = (
        os.getenv("MIX_SAVING_API_BASE")
        or os.getenv("MIX_SAVING_BACKEND_URL")
        or ""
    )
    return _normalize_api_base(raw)


def _pick_remote_id(obj: dict[str, object]) -> str | None:
    for key in ("remote_id", "id", "job_id", "task_id"):
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _jobs_collection_url(base: str) -> str:
    path = os.getenv("MIX_BACKEND_JOBS_PATH", _DEFAULT_JOB_PATH).strip() or _DEFAULT_JOB_PATH
    if not path.startswith("/"):
        path = "/" + path
    return f"{base}{path}"


def _status_url(base: str, remote_id: str) -> str:
    path = os.getenv("MIX_BACKEND_JOBS_PATH", _DEFAULT_JOB_PATH).strip() or _DEFAULT_JOB_PATH
    if not path.startswith("/"):
        path = "/" + path
    return f"{base}{path.rstrip('/')}/{remote_id}"


async def _read_json(resp: aiohttp.ClientResponse) -> dict[str, object]:
    try:
        body = await resp.text()
        return json.loads(body) if body else {}
    except json.JSONDecodeError:
        return {}


def _http_error_result(
    job_id: str, status: int, payload: dict[str, object]
) -> TaskResult:
    code = str(payload.get("error_code") or "").upper()
    if not code:
        if status == 400:
            code = "INVALID_INPUT"
        elif status == 413:
            code = "FILE_TOO_LARGE"
        elif status == 404:
            code = "NOT_FOUND"
        else:
            code = "BACKEND_HTTP_ERROR"
    return TaskResult(
        job_id=job_id,
        status=JobStatus.FAILED,
        message=str(payload.get("message") or f"HTTP {status}"),
        detail={"error_code": code, "http_status": status, "body": payload},
    )


async def _save_remote_file(
    session: aiohttp.ClientSession,
    download_url: str,
) -> pathlib.Path:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".bin")
    tmp_path = pathlib.Path(tmp.name)
    tmp.close()
    try:
        async with session.get(download_url) as resp:
            if resp.status >= 400:
                text = await resp.text()
                raise RuntimeError(f"artifact fetch failed {resp.status}: {text[:200]}")
            with tmp_path.open("wb") as fh:
                async for chunk in resp.content.iter_chunked(1024 * 512):
                    fh.write(chunk)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    return tmp_path


async def execute_remote_download(
    job: Job,
    *,
    session: aiohttp.ClientSession,
    api_base: str,
) -> TaskResult:
    base = _normalize_api_base(api_base)
    if not base:
        return TaskResult(
            job_id=job.id,
            status=_API_BASE_ERROR.status,
            message=_API_BASE_ERROR.message,
            detail=dict(_API_BASE_ERROR.detail),
        )

    collection_url = _jobs_collection_url(base)
    body = {"kind": job.kind, "payload": job.payload}
    try:
        async with session.post(collection_url, json=body) as resp:
            payload = await _read_json(resp)
            if resp.status >= 400:
                return _http_error_result(job.id, resp.status, payload)
            remote_id = _pick_remote_id(payload)
            if not remote_id:
                return TaskResult(
                    job_id=job.id,
                    status=JobStatus.FAILED,
                    message="Backend response missing job identifier",
                    detail={"error_code": "BACKEND_PROTOCOL", "body": payload},
                )
    except aiohttp.ClientError as exc:
        log.warning("download submit failed", extra={"job_id": job.id, "error": str(exc)})
        return TaskResult(
            job_id=job.id,
            status=JobStatus.FAILED,
            message="Could not reach downloader service.",
            detail={"error_code": "BACKEND_UNAVAILABLE", "error": str(exc)},
        )

    poll_url = _status_url(base, remote_id)
    deadline = time.monotonic() + _DEFAULT_MAX_WAIT
    while True:
        if time.monotonic() > deadline:
            return TaskResult(
                job_id=job.id,
                status=JobStatus.FAILED,
                message="Downloader job timed out.",
                detail={"error_code": "BACKEND_TIMEOUT", "remote_id": remote_id},
            )
        try:
            async with session.get(poll_url) as resp:
                payload = await _read_json(resp)
                if resp.status >= 400:
                    return _http_error_result(job.id, resp.status, payload)
        except aiohttp.ClientError as exc:
            log.warning("download poll failed", extra={"job_id": job.id, "error": str(exc)})
            return TaskResult(
                job_id=job.id,
                status=JobStatus.FAILED,
                message="Lost connection while waiting for the file.",
                detail={"error_code": "BACKEND_UNAVAILABLE", "error": str(exc)},
            )

        status_raw = str(payload.get("status") or payload.get("state") or "").lower()
        if status_raw in {"queued", "pending", "processing", "running", "active"}:
            await asyncio.sleep(_DEFAULT_POLL_INTERVAL)
            continue
        if status_raw in {"failed", "error", "rejected"}:
            code = str(payload.get("error_code") or "BACKEND_FAILURE").upper()
            return TaskResult(
                job_id=job.id,
                status=JobStatus.FAILED,
                message=str(payload.get("message") or "Download failed"),
                detail={"error_code": code, "remote_id": remote_id, "body": payload},
            )
        if status_raw in {"completed", "done", "success", "finished"}:
            artifact = payload.get("artifact")
            if not isinstance(artifact, dict):
                artifact = {}
            file_path = artifact.get("file_path") or artifact.get("local_path")
            download_url = (
                artifact.get("download_url")
                or artifact.get("url")
                or artifact.get("signed_url")
            )
            filename = artifact.get("filename") or artifact.get("name")

            if isinstance(file_path, str) and file_path:
                path = pathlib.Path(file_path)
                if not path.is_file():
                    return TaskResult(
                        job_id=job.id,
                        status=JobStatus.FAILED,
                        message="Backend reported a missing file on disk.",
                        detail={
                            "error_code": "BACKEND_PROTOCOL",
                            "path": file_path,
                        },
                    )
                detail: dict[str, object] = {
                    "output_path": str(path),
                    "remote_id": remote_id,
                }
                if isinstance(filename, str):
                    detail["filename"] = filename
                return TaskResult(
                    job_id=job.id,
                    status=JobStatus.COMPLETED,
                    message="ready",
                    detail=detail,
                )

            if isinstance(download_url, str) and download_url.strip():
                try:
                    local = await _save_remote_file(session, download_url.strip())
                except Exception as exc:  # noqa: BLE001
                    return TaskResult(
                        job_id=job.id,
                        status=JobStatus.FAILED,
                        message="Failed to download prepared artifact.",
                        detail={
                            "error_code": "ARTIFACT_FETCH_FAILED",
                            "error": str(exc),
                        },
                    )
                detail = {
                    "output_path": str(local),
                    "remote_id": remote_id,
                    "temp_file": True,
                }
                if isinstance(filename, str):
                    detail["filename"] = filename
                return TaskResult(
                    job_id=job.id,
                    status=JobStatus.COMPLETED,
                    message="ready",
                    detail=detail,
                )

            return TaskResult(
                job_id=job.id,
                status=JobStatus.FAILED,
                message="Backend completed without a retrievable artifact.",
                detail={"error_code": "BACKEND_PROTOCOL", "body": payload},
            )

        await asyncio.sleep(_DEFAULT_POLL_INTERVAL)


DownloadProcessor = Callable[[Job], Awaitable[TaskResult]]


def build_download_processor(
    *,
    session: aiohttp.ClientSession,
    api_base: str,
    cache: DownloadCache | None = None,
) -> DownloadProcessor:
    """
    Downloader-bound processor for ``Worker`` ``processors`` map.

    When ``cache`` is set, matches reservations from :meth:`TaskPipeline.submit_download`
    by committing on success and aborting on any non-completed status.
    """

    async def _run(job: Job) -> TaskResult:
        result = await execute_remote_download(job, session=session, api_base=api_base)
        if cache is not None:
            key = cache.dedupe_key_for_payload(job.payload)
            if result.status == JobStatus.COMPLETED:
                await cache.commit(key)
            else:
                await cache.abort(key)
        return result

    return _run
