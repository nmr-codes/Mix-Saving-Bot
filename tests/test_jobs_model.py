from __future__ import annotations

from core.contracts.types import SubmitDownloadRequest
from services.jobs.model import job_record_to_public_dict, make_job_record, new_job_id


def test_make_job_record_carries_dedupe_key() -> None:
    req: SubmitDownloadRequest = {
        "source_url": "https://x",
        "correlation_id": "c",
        "chat": {"chat_id": 1, "user_id": 2},
    }
    jid = new_job_id()
    rec = make_job_record(jid, "queued", req, dedupe_key="k1")
    assert rec["dedupe_key"] == "k1"
    pub = job_record_to_public_dict(rec)
    assert pub["job_id"] == jid
