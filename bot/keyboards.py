"""Inline keyboards shared by routers."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def build_download_choice_keyboard(session_token: str) -> InlineKeyboardMarkup:
    v = InlineKeyboardButton(
        text="Download Video",
        callback_data=f"dl:v:{session_token}",
    )
    a = InlineKeyboardButton(
        text="Download Audio",
        callback_data=f"dl:a:{session_token}",
    )
    return InlineKeyboardMarkup(inline_keyboard=[[v], [a]])
