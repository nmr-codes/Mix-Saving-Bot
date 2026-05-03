from __future__ import annotations

import pytest

from core.contracts.types import SubmitDownloadRequest
from services.jobs.model import make_job_record, new_job_id
from services.jobs.terminal_waiter import JobTerminalWaiter


def _req() -> SubmitDownloadRequest:
    return {
        "source_url": "https://youtube.com/x",
        "correlation_id": "c",
        "chat": {"chat_id": 1, "user_id": 2},
    }


@pytest.mark.asyncio
async def test_subscribe_waits_for_publish() -> None:
    w = JobTerminalWaiter()
    job_id = new_job_id()
    rec = make_job_record(job_id, "queued", _req())
    fut = await w.subscribe(job_id, snapshot=rec)
    assert not fut.done()

    done = make_job_record(job_id, "succeeded", _req())
    done["outputs"] = [
        {"kind": "local_path", "value": "/tmp/x", "byte_size": 1},
    ]
    await w.publish_terminal(done)

    out = await fut
    assert out["status"] == "succeeded"


@pytest.mark.asyncio
async def test_subscribe_already_terminal_snapshot_returns_immediately() -> None:
    w = JobTerminalWaiter()
    job_id = new_job_id()
    rec = make_job_record(job_id, "failed", _req())
    rec["error_code"] = "X"
    rec["error_message_safe"] = "boom"
    fut = await w.subscribe(job_id, snapshot=rec)
    assert fut.done()
    row = fut.result()
    assert row["status"] == "failed"
