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


@pytest.mark.asyncio
async def test_metrics_histogram_observe_truncates_large_samples() -> None:
    reset_metrics()
    m = get_metrics()
    for _ in range(1200):
        await m.observe_duration_sec("d", 0.001)
    snap = m.snapshot()
    assert "d" in snap["histogram_last"]

