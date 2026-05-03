from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BeforeValidator, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def clear_settings_cache() -> None:
    """Reset cached Settings (needed in tests after changing ``os.environ``)."""
    get_settings.cache_clear()


def _default_allowed_hosts() -> frozenset[str]:
    return frozenset(
        {
            "www.youtube.com",
            "youtube.com",
            "youtu.be",
            "m.youtube.com",
            "www.instagram.com",
            "instagram.com",
            "www.tiktok.com",
            "tiktok.com",
            "vm.tiktok.com",
            "vt.tiktok.com",
            "www.facebook.com",
            "facebook.com",
            "m.facebook.com",
            "twitter.com",
            "x.com",
            "www.twitter.com",
        }
    )


def parse_allowed_hosts(value: Any) -> frozenset[str]:
    """Parse ``MIX_ALLOWED_HOSTS`` from env: CSV, JSON array, or ``*`` (unrestricted)."""
    if isinstance(value, frozenset):
        return value
    if value is None:
        return frozenset()
    if isinstance(value, list):
        return frozenset(str(x).strip().lower() for x in value if str(x).strip())
    if isinstance(value, str):
        text = value.strip()
        if text == "*":
            return frozenset()
        if not text:
            return _default_allowed_hosts()
        if text.startswith("["):
            decoded = json.loads(text)
            if not isinstance(decoded, list):
                raise ValueError("MIX_ALLOWED_HOSTS JSON must be a JSON array of strings.")
            return frozenset(str(x).strip().lower() for x in decoded if str(x).strip())
        return frozenset(h.strip().lower() for h in text.split(",") if h.strip())
    raise TypeError(f"ALLOWED_HOSTS: unexpected input type {type(value)!r}")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MIX_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    BOT_TOKEN: str = Field(default="", description="Telegram bot token")

    QUEUE_BACKEND: Literal["memory", "redis"] = "memory"
    REDIS_URL: str | None = None
    REDIS_QUEUE_STREAM_KEY: str = "mixdl:jobs"
    REDIS_QUEUE_GROUP: str = "mixdl-workers"
    REDIS_QUEUE_CONSUMER_NAME: str = "worker-1"

    CACHE_BACKEND: Literal["file", "file_redis_meta"] = "file"
    CACHE_ROOT_DIR: Path = Field(default=Path("/tmp/mix-saving-cache"))

    JOB_REPO_BACKEND: Literal["memory"] = "memory"

    MAX_CONCURRENT_DOWNLOADS: int = 2
    DOWNLOAD_DEADLINE_SEC: int = 600
    MAX_OUTPUT_BYTES: int = 2_000_000_000
    MAX_DURATION_SEC: int = 7200

    ALLOWED_HOSTS: Annotated[
        frozenset[str],
        NoDecode,
        BeforeValidator(parse_allowed_hosts),
    ] = Field(default_factory=_default_allowed_hosts)

    LOG_LEVEL: str = "INFO"

    HIGH_WATER_QUEUE_DEPTH: int = 200

    RATE_LIMIT_MAX_EVENTS: int = 35
    RATE_LIMIT_WINDOW_SECONDS: float = 60.0

    YTDLP_CONFIG_PATH: Path | None = None

    @field_validator("BOT_TOKEN", mode="before")
    @classmethod
    def _strip_bot_token(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("LOG_LEVEL", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().upper() or "INFO"
        return value

    @field_validator("CACHE_ROOT_DIR", mode="before")
    @classmethod
    def _expand_path(cls, v: object) -> Path:
        if v is None:
            return Path("/tmp/mix-saving-cache")
        return Path(v).expanduser().resolve()

    @field_validator("YTDLP_CONFIG_PATH", mode="before")
    @classmethod
    def _optional_path(cls, v: object) -> Path | None:
        if v is None or v == "":
            return None
        return Path(v).expanduser().resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
