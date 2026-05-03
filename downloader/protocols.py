from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypedDict


class DownloadProgress(TypedDict, total=False):
    pct: float
    stage: Literal["queued", "starting", "downloading", "merging", "finished"]
    message: str


@dataclass(frozen=True)
class DownloadConstraints:
    max_duration_sec: int
    max_file_size_bytes: int
    allowed_hosts: frozenset[str]


@dataclass(frozen=True)
class DownloadJobContext:
    job_id: str
    source_url: str
    constraints: DownloadConstraints
    requested_format_id: str | None
    work_dir: str


DownloadProgressCallback = Callable[[DownloadProgress], Awaitable[None]]


class MediaDownloader(Protocol):
    async def probe(self, ctx: DownloadJobContext) -> dict[str, Any]:
        """Lightweight metadata; JSON-serializable only."""

    async def download(
        self,
        ctx: DownloadJobContext,
        on_progress: DownloadProgressCallback,
    ) -> list[dict[str, Any]]:
        """Materialize artifacts; returns per-file descriptors with ``local_path``."""
