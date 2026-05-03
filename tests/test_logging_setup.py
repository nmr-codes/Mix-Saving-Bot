from __future__ import annotations

import json
import logging
from typing import Generator

import pytest

from core.logging_setup import JsonFormatter, get_logger, setup_json_logging


@pytest.fixture(autouse=True)
def _restore_root_logging_after_test() -> Generator[None, None, None]:
    root = logging.getLogger()
    old_handlers = list(root.handlers)
    old_level = root.level
    yield
    root.handlers.clear()
    for h in old_handlers:
        root.addHandler(h)
    root.setLevel(old_level)


def test_json_formatter_basic() -> None:
    fmt = JsonFormatter()
    lr = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="p",
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    lr.job_id = "j1"
    out = fmt.format(lr)
    data = json.loads(out)
    assert data["level"] == "INFO"
    assert data["logger"] == "test"
    assert data["msg"] == "hello"
    assert data["job_id"] == "j1"


def test_json_formatter_with_exception() -> None:
    import sys

    fmt = JsonFormatter()
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        lr = logging.LogRecord("x", logging.ERROR, "p", 1, "e", (), sys.exc_info())
    text = fmt.format(lr)
    data = json.loads(text)
    assert "RuntimeError" in data["exc_info"]


def test_setup_json_logging_registers_handler() -> None:
    setup_json_logging(logging.WARNING)
    root = logging.getLogger()
    assert root.level == logging.WARNING
    assert len(root.handlers) == 1


def test_get_logger_returns_named_logger() -> None:
    log = get_logger("my.mod")
    assert log.name == "my.mod"
