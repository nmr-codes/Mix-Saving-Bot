from __future__ import annotations

import time

import pytest

from core.contracts.types import SubmitDownloadRequest
from services.jobs.model import make_job_record, new_job_id
from services.jobs.repository import InMemoryJobRepository
from services.jobs.service import JobServiceImpl
from services.jobs.terminal_waiter import JobTerminalWaiter


def _minimal_req(
    cid: str = "corr", chat_id: int = 10, uid: int = 20, reply: int | None = 3
) -> SubmitDownloadRequest:
    ctx: SubmitDownloadRequest = {
        "source_url": "https://youtube.com/x",
        "correlation_id": cid,
        "chat": {"chat_id": chat_id, "user_id": uid},
    }
    if reply is not None:
        ctx["chat"]["reply_to_message_id"] = reply
    return ctx


@pytest.mark.asyncio
async def test_repository_save_and_get_roundtrip() -> None:
    r = InMemoryJobRepository()
    rec = make_job_record(new_job_id(), "queued", _minimal_req())
    await r.save(rec)
    got = await r.get(rec["job_id"])
    assert got is not None
    assert got["status"] == "queued"


@pytest.mark.asyncio
async def test_dedupe_prevents_duplicate_active_job() -> None:
    repo = InMemoryJobRepository()
    waiter_obj = JobTerminalWaiter()
    svc = JobServiceImpl(repo, waiter=waiter_obj)

    dedupe_key = "chat:format"
    req = _minimal_req(cid="first")
    j1, enq1 = await svc.submit(req, dedupe_key=dedupe_key)
    assert enq1 is True

    j2, enq2 = await svc.submit(_minimal_req(cid="second"), dedupe_key=dedupe_key)
    assert enq2 is False
    assert j2["job_id"] == j1["job_id"]


@pytest.mark.asyncio
async def test_find_active_ignores_succeeded_duplicate_key() -> None:
    repo = InMemoryJobRepository()
    jid = new_job_id()
    rec = make_job_record(jid, "queued", _minimal_req(), dedupe_key="k")
    await repo.save(rec)
    rec_done = dict(rec)
    rec_done["status"] = "succeeded"
    rec_done["updated_at_unix"] = time.time()
    await repo.save(rec_done)

    dup = await repo.find_active_by_dedupe("k")
    assert dup is None
