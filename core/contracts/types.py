from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

CACHE_PREFIX = "mixdl"

QueueStatusLiteral = Literal["queued", "running", "succeeded", "failed", "canceled"]


class ChatContext(TypedDict):
    chat_id: int
    user_id: int
    locale: NotRequired[str]
    reply_to_message_id: NotRequired[int]


class SubmitDownloadRequest(TypedDict):
    source_url: str
    correlation_id: str
    chat: ChatContext
    requested_format_id: NotRequired[str]
    """yt-dlp format string, or preset ``audio`` / ``video`` (default)."""


class JobOutputRef(TypedDict):
    kind: Literal["telegram_file_id", "local_path", "cache_key"]
    value: str
    mime_type: NotRequired[str]
    byte_size: NotRequired[int]


class JobRecord(TypedDict):
    job_id: str
    status: QueueStatusLiteral
    request: SubmitDownloadRequest
    created_at_unix: float
    updated_at_unix: float
    error_code: NotRequired[str]
    error_message_safe: NotRequired[str]
    outputs: NotRequired[list[JobOutputRef]]
    dedupe_key: NotRequired[str]


class QueueMessage(TypedDict):
    job_id: str
    correlation_id: str
    enqueued_at_unix: float


class CacheEntryDict(TypedDict):
    cache_key: str
    local_path: str
    byte_size: int
    created_at_unix: float
    content_hash: NotRequired[str]
