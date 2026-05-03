from __future__ import annotations

import pytest

from bot import formatters
from core.contracts.types import JobRecord


@pytest.mark.parametrize(
    ("jid", "sub"),
    [
        ("0123456789abcdef", "01234567"),
    ],
)
def test_fmt_queued_contains_prefix(jid: str, sub: str) -> None:
    text = formatters.fmt_queued(jid)
    assert sub in text


def test_fmt_busy_and_timeout_plain_text() -> None:
    busy = formatters.fmt_busy()
    assert "busy" in busy.lower() or "queue" in busy.lower()
    to = formatters.fmt_timeout()
    assert "timed out" in to.lower() or "timeout" in to.lower()


def test_fmt_failed_fallback_without_code() -> None:
    rec: JobRecord = {
        "job_id": "x",
        "status": "failed",
        "request": {
            "source_url": "u",
            "correlation_id": "c",
            "chat": {"chat_id": 1, "user_id": 2},
        },
        "created_at_unix": 0,
        "updated_at_unix": 0,
        "error_message_safe": "oops",
    }
    assert formatters.fmt_failed(rec) == "oops"


def test_fmt_failed_includes_code() -> None:
    rec: JobRecord = {
        "job_id": "x",
        "status": "failed",
        "request": {
            "source_url": "u",
            "correlation_id": "c",
            "chat": {"chat_id": 1, "user_id": 2},
        },
        "created_at_unix": 0,
        "updated_at_unix": 0,
        "error_code": "E",
        "error_message_safe": "bad",
    }
    out = formatters.fmt_failed(rec)
    assert "bad" in out
    assert "E" in out
