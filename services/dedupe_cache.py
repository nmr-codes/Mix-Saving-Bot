from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Literal

from services.logging_config import get_logger

log = get_logger("services.dedupe_cache")


class CacheBackendError(Exception):
    """Raised when a cache operation fails in a way callers may want to handle."""


def default_dedupe_key(payload: dict[str, Any]) -> str:
    url = payload.get("url") or payload.get("source_url") or ""
    mix_id = payload.get("mix_id") or ""
    media = payload.get("media") or ""
    raw = f"{url}\n{mix_id}\n{media}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class DownloadCache:
    """
    Prevents duplicate downloads for the same logical resource.

    - In-memory authoritative sets for completed URLs and in-flight work.
    - Optional disk index (JSON lines) for cross-process hints; failures degrade
      to memory-only and emit structured warnings (filesystem edge cases).

    Use :meth:`try_reserve` / :meth:`commit` / :meth:`abort` so parallel workers
    cannot double-download the same key.
    """

    def __init__(
        self,
        *,
        index_path: Path | str | None = None,
        dedupe_key_fn=default_dedupe_key,
    ) -> None:
        self._lock = asyncio.Lock()
        self._completed: set[str] = set()
        self._in_flight: dict[str, str] = {}
        self._index_path = Path(index_path) if index_path else None
        self._dedupe_key_fn = dedupe_key_fn
        self._disk_enabled = bool(self._index_path)

    def dedupe_key_for_payload(self, payload: dict[str, Any]) -> str:
        return self._dedupe_key_fn(payload)

    async def is_duplicate(self, key: str) -> bool:
        """Read-only check: completed or actively being processed by another job."""
        async with self._lock:
            if key in self._completed or key in self._in_flight:
                return True
            if self._index_path and self._disk_enabled:
                try:
                    if self._key_on_disk_index(key):
                        self._completed.add(key)
                        return True
                except OSError as exc:
                    log.warning(
                        "cache disk read failed; continuing memory-only",
                        extra={"key": key, "error": str(exc)},
                    )
                    self._disk_enabled = False
            return False

    async def try_reserve(
        self, key: str, job_id: str
    ) -> Literal["reserved", "duplicate"]:
        """
        Reserve ``key`` for ``job_id``.

        If the same ``job_id`` already holds the reservation (e.g. recovered
        after a worker crash before commit/abort), this returns ``reserved``.
        """
        async with self._lock:
            if key in self._completed:
                return "duplicate"
            if key in self._in_flight:
                if self._in_flight[key] == job_id:
                    return "reserved"
                return "duplicate"
            if self._index_path and self._disk_enabled:
                try:
                    if self._key_on_disk_index(key):
                        self._completed.add(key)
                        return "duplicate"
                except OSError as exc:
                    log.warning(
                        "cache disk read failed; continuing memory-only",
                        extra={"key": key, "error": str(exc)},
                    )
                    self._disk_enabled = False
            self._in_flight[key] = job_id
            return "reserved"

    async def commit(self, key: str) -> None:
        """Mark key as successfully completed and persist hint (best-effort)."""
        async with self._lock:
            self._in_flight.pop(key, None)
            self._completed.add(key)
            if self._index_path and self._disk_enabled:
                try:
                    self._append_disk_index(key)
                except OSError as exc:
                    log.warning(
                        "cache disk write failed; memory cache still active",
                        extra={"key": key, "error": str(exc)},
                    )
                    self._disk_enabled = False

    async def abort(self, key: str) -> None:
        """Release reservation without marking completed (handler failed)."""
        async with self._lock:
            self._in_flight.pop(key, None)

    async def mark_complete(self, key: str) -> None:
        """
        Backwards-compatible helper: reserve must have succeeded; same as commit.
        """
        await self.commit(key)

    async def reset_memory(self) -> None:
        """Test helper: clears in-memory entries only."""
        async with self._lock:
            self._completed.clear()
            self._in_flight.clear()

    def _key_on_disk_index(self, key: str) -> bool:
        path = self._index_path
        assert path is not None
        if not path.exists():
            return False
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            raise
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("key") == key:
                return True
        return False

    def _append_disk_index(self, key: str) -> None:
        path = self._index_path
        assert path is not None
        path.parent.mkdir(parents=True, exist_ok=True)
        record = json.dumps({"key": key}, ensure_ascii=False) + os.linesep
        with path.open("a", encoding="utf-8") as fh:
            fh.write(record)
            fh.flush()
            os.fsync(fh.fileno())
