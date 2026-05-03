from __future__ import annotations

from services.queue.redis_queue import _parse_message


def test_parse_message_fields() -> None:
    out = _parse_message(
        {
            "job_id": "111",
            "correlation_id": "abc",
            "enqueued_at_unix": "12.5",
        }
    )
    assert out["job_id"] == "111"
    assert out["correlation_id"] == "abc"
    assert out["enqueued_at_unix"] == 12.5
