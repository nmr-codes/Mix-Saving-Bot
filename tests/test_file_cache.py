from __future__ import annotations

import pathlib

import pytest

from services.cache.file_cache import FileCacheStore


@pytest.mark.asyncio
async def test_file_cache_roundtrip_put_get(tmp_path: pathlib.Path) -> None:
    store = FileCacheStore(tmp_path / "blobs")

    blob = pathlib.Path(tmp_path / "src.bin")
    blob.write_bytes(b"hello-world")

    ent = await store.put_from_path("digest123", str(blob))
    assert ent["byte_size"] == len(b"hello-world")

    fetched = await store.get("digest123")
    assert fetched is not None
    assert pathlib.Path(fetched["local_path"]).read_bytes() == b"hello-world"


@pytest.mark.asyncio
async def test_file_cache_idempotent_second_put_same_key(tmp_path: pathlib.Path) -> None:
    store = FileCacheStore(tmp_path / "c")

    blob = pathlib.Path(tmp_path / "a.bin")
    blob.write_bytes(b"x")
    e1 = await store.put_from_path("k", str(blob))
    e2 = await store.put_from_path("k", str(blob))
    assert e1["local_path"] == e2["local_path"]
