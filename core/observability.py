from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Any


class Metrics:
    """Lightweight in-process counters (replace with Prometheus in production)."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._counters: dict[str, int] = defaultdict(int)
        self._histogram_samples: dict[str, list[float]] = defaultdict(list)

    async def inc(self, name: str, value: int = 1) -> None:
        async with self._lock:
            self._counters[name] += value

    async def observe_duration_sec(self, name: str, seconds: float) -> None:
        async with self._lock:
            self._histogram_samples[name].append(seconds)
            if len(self._histogram_samples[name]) > 1000:
                self._histogram_samples[name] = self._histogram_samples[name][-500:]

    def snapshot(self) -> dict[str, Any]:
        return {
            "counters": dict(self._counters),
            "histogram_last": {
                k: (sum(v) / len(v) if v else 0.0) for k, v in self._histogram_samples.items()
            },
        }


_metrics: Metrics | None = None


def reset_metrics() -> None:
    """Replace the singleton metrics collector (primarily for tests)."""
    global _metrics
    _metrics = Metrics()


def get_metrics() -> Metrics:
    global _metrics
    if _metrics is None:
        _metrics = Metrics()
    return _metrics


def monotonic_now() -> float:
    return time.monotonic()
