from __future__ import annotations

import asyncio
import os
import shutil
import time
import uuid
from pathlib import Path

from core.contracts.types import CACHE_PREFIX, CacheEntryDict
from core.logging_setup import get_logger

log = get_logger("services.cache.file")


class FileCacheStore:
    """On-disk blobs under ``cache_root``, keyed by ``cache_key`` (hex digest)."""

    def __init__(self, cache_root: Path) -> None:
        self._root = cache_root.expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    def _blob_path(self, cache_key: str) -> Path:
        safe = cache_key.replace("..", "").replace("/", "").replace("\\", "")[:240]
        return self._root / f"{CACHE_PREFIX}_{safe}"

    async def get(self, cache_key: str) -> CacheEntryDict | None:
        async with self._lock:
            path = self._blob_path(cache_key)
            if not path.is_file():
                return None
            st = path.stat()
            entry: CacheEntryDict = {
                "cache_key": cache_key,
                "local_path": str(path),
                "byte_size": st.st_size,
                "created_at_unix": min(st.st_ctime, st.st_mtime),
            }
            return entry

    async def put_from_path(self, cache_key: str, src_path: str) -> CacheEntryDict:
        src = Path(src_path).resolve()
        if not src.is_file():
            raise FileNotFoundError(src_path)
        dest = self._blob_path(cache_key)

        async with self._lock:
            if dest.is_file():
                st = dest.stat()
                return {
                    "cache_key": cache_key,
                    "local_path": str(dest),
                    "byte_size": st.st_size,
                    "created_at_unix": min(st.st_ctime, st.st_mtime),
                }
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(dest.suffix + f".{uuid.uuid4().hex}.tmp")
            try:
                try:
                    os.link(src, tmp)
                except OSError:
                    shutil.copy2(src, tmp)
                os.replace(tmp, dest)
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise
            st = dest.stat()
            return {
                "cache_key": cache_key,
                "local_path": str(dest),
                "byte_size": st.st_size,
                "created_at_unix": time.time(),
            }

    async def delete(self, cache_key: str) -> None:
        path = self._blob_path(cache_key)
        path.unlink(missing_ok=True)

    async def touch_ttl(self, cache_key: str) -> None:
        path = self._blob_path(cache_key)
        if path.is_file():
            now = time.time()
            os.utime(path, (now, now))
