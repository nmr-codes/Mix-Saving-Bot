from __future__ import annotations

import pytest

from core.observability import get_metrics, reset_metrics


@pytest.mark.asyncio
async def test_metrics_counters_increment_resettable() -> None:
    reset_metrics()
    m = get_metrics()
    await m.inc("x")
    snap = m.snapshot()
    assert snap["counters"]["x"] == 1
