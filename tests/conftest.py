from __future__ import annotations

import pytest

from core.observability import reset_metrics
from core.settings import clear_settings_cache


@pytest.fixture(autouse=True)
def _reset_cached_settings_between_tests() -> None:
    clear_settings_cache()
    yield
    clear_settings_cache()


@pytest.fixture(autouse=True)
def _fresh_metrics_every_test() -> None:
    reset_metrics()
    yield
