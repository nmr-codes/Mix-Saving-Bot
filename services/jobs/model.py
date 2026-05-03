from __future__ import annotations

import time
import uuid
from typing import Literal, cast

from core.contracts.types import JobRecord, SubmitDownloadRequest

QueueStatusLiteral = Literal["queued", "running", "succeeded", "failed", "canceled"]


def new_job_id() -> str:
    return str(uuid.uuid4())


def make_job_record(
    job_id: str,
    status: QueueStatusLiteral,
    request: SubmitDownloadRequest,
    *,
    dedupe_key: str | None = None,
) -> JobRecord:
    now = time.time()
    rec: JobRecord = {
        "job_id": job_id,
        "status": status,
        "request": request,
        "created_at_unix": now,
        "updated_at_unix": now,
    }
    if dedupe_key is not None:
        rec["dedupe_key"] = dedupe_key
    return rec


def job_record_to_public_dict(rec: JobRecord) -> dict[str, object]:
    """Narrow copy for logging / API responses."""
    return cast(dict[str, object], dict(rec))
