from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.dedupe_cache import DownloadCache, default_dedupe_key


def test_default_dedupe_key_stable() -> None:
    p = {"url": "https://x", "media": "audio"}
    assert default_dedupe_key(p) == default_dedupe_key(dict(p))


@pytest.mark.asyncio
async def test_try_reserve_and_commit() -> None:
    c = DownloadCache()
    assert await c.try_reserve("k1", "job-a") == "reserved"
    assert await c.try_reserve("k1", "job-b") == "duplicate"
    assert await c.try_reserve("k1", "job-a") == "reserved"
    await c.commit("k1")
    assert await c.try_reserve("k1", "job-c") == "duplicate"


@pytest.mark.asyncio
async def test_abort_releases_key() -> None:
    c = DownloadCache()
    assert await c.try_reserve("k2", "j1") == "reserved"
    await c.abort("k2")
    assert await c.try_reserve("k2", "j2") == "reserved"


@pytest.mark.asyncio
async def test_duplicate_after_commit() -> None:
    c = DownloadCache()
    await c.try_reserve("k3", "j")
    await c.commit("k3")
    assert await c.is_duplicate("k3") is True


@pytest.mark.asyncio
async def test_disk_index_roundtrip(tmp_path: Path) -> None:
    idx = tmp_path / "idx.jsonl"
    c = DownloadCache(index_path=idx)
    await c.try_reserve("diskkey", "jid")
    await c.commit("diskkey")
    lines = idx.read_text(encoding="utf-8").strip().splitlines()
    row = json.loads(lines[-1])
    assert row["key"] == "diskkey"
    fresh = DownloadCache(index_path=idx)
    assert await fresh.is_duplicate("diskkey") is True


@pytest.mark.asyncio
async def test_reset_memory() -> None:
    c = DownloadCache()
    await c.try_reserve("z", "j")
    await c.reset_memory()
    assert await c.try_reserve("z", "j") == "reserved"
