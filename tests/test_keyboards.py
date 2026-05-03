from __future__ import annotations

import uuid

from bot.keyboards import build_download_choice_keyboard


def test_keyboard_callback_lengths_ok_for_telegram() -> None:
    token = uuid.uuid4().hex
    kb = build_download_choice_keyboard(token)
    rows = kb.inline_keyboard
    texts = "".join(btn.callback_data or "" for row in rows for btn in row)
    assert token in texts
    for row in kb.inline_keyboard:
        for btn in row:
            data = btn.callback_data or ""
            assert len(data.encode("utf-8")) <= 64, data


def test_keyboard_labels() -> None:
    kb = build_download_choice_keyboard("a" * 32)
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert any("Video" in t for t in texts)
    assert any("Audio" in t for t in texts)
