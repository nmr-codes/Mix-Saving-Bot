"""Backwards-compatible re-export — prefer :mod:`core.logging_setup`."""

from core.logging_setup import JsonFormatter, get_logger, setup_json_logging

__all__ = ["JsonFormatter", "get_logger", "setup_json_logging"]
