from __future__ import annotations

import hashlib
from urllib.parse import urlparse

from core.contracts.errors import SanitizeError
from downloader.protocols import DownloadConstraints


def normalize_url(raw: str) -> str:
    return raw.strip()


def validate_for_download(url: str, constraints: DownloadConstraints) -> None:
    trimmed = normalize_url(url)
    if not trimmed:
        raise SanitizeError("URL is empty.", code="INVALID_URL")
    parsed = urlparse(trimmed)
    if parsed.scheme not in ("http", "https"):
        raise SanitizeError(
            f"Only http/https URLs are allowed (got {parsed.scheme!r}).",
            code="SCHEME_UNSUPPORTED",
        )
    host = (parsed.hostname or "").lower()
    if not host:
        raise SanitizeError("URL has no host.", code="INVALID_URL")
    if constraints.allowed_hosts and host not in constraints.allowed_hosts:
        allowed = ", ".join(sorted(constraints.allowed_hosts))
        raise SanitizeError(
            f"Host {host!r} is not in the allowed list: {allowed}",
            code="HOST_NOT_ALLOWED",
        )


def canonical_cache_key(source_url: str, format_id: str | None) -> str:
    raw = f"{normalize_url(source_url)}\n{format_id_digest_part(format_id)}".encode(
        "utf-8",
    )
    return hashlib.sha256(raw).hexdigest()


def format_id_digest_part(format_id: str | None) -> str:
    return format_id if format_id is not None else "default"
