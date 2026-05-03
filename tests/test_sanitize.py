from __future__ import annotations

from dataclasses import replace

import pytest

from core.contracts.errors import SanitizeError
from downloader.protocols import DownloadConstraints
from downloader.sanitize import canonical_cache_key, normalize_url, validate_for_download


def _constraints(**kwargs: object) -> DownloadConstraints:
    base = DownloadConstraints(
        max_duration_sec=3600,
        max_file_size_bytes=1_000_000_000,
        allowed_hosts=frozenset({"youtube.com"}),
    )
    return replace(base, **kwargs) if kwargs else base


@pytest.mark.parametrize(
    ("bad", "code"),
    [
        ("", "INVALID_URL"),
        ("ftp://youtube.com/watch", "SCHEME_UNSUPPORTED"),
        ("http:///nohost", "INVALID_URL"),
    ],
)
def test_validate_url_rejects_bad(bad: str, code: str) -> None:
    c = _constraints()
    with pytest.raises(SanitizeError) as ei:
        validate_for_download(bad, c)
    assert getattr(ei.value, "code", "") == code


def test_validate_rejects_foreign_host_when_restricted() -> None:
    c = _constraints(allowed_hosts=frozenset({"youtube.com"}))
    with pytest.raises(SanitizeError) as exc:
        validate_for_download("https://evil.example/video", c)
    assert exc.value.code == "HOST_NOT_ALLOWED"


def test_validate_allows_all_when_host_list_empty() -> None:
    c = DownloadConstraints(
        max_duration_sec=3600,
        max_file_size_bytes=1,
        allowed_hosts=frozenset(),
    )
    validate_for_download("https://example.org/x", c)


def test_canonical_cache_key_formats() -> None:
    assert canonical_cache_key("https://x/a", None) == canonical_cache_key("https://x/a", None)
    assert canonical_cache_key("https://x/a ", None) == canonical_cache_key("https://x/a", None)


def test_normalize_url() -> None:
    assert normalize_url("  hello  ") == "hello"
