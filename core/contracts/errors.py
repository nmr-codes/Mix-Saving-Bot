from __future__ import annotations


class SanitizeError(ValueError):
    """Invalid URL or disallowed host (user-facing message in ``args[0]``)."""

    def __init__(self, message: str, *, code: str = "INVALID") -> None:
        super().__init__(message)
        self.code = code


class DownloaderTransientError(Exception):
    """Retryable failure (network, source 5xx)."""


class DownloaderFatalError(Exception):
    """Non-retryable failure (unsupported, geo, private)."""
