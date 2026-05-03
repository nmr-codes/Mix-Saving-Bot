from __future__ import annotations

from core.settings import (
    Settings,
    clear_settings_cache,
    get_settings,
    parse_allowed_hosts,
)


def test_parse_allowed_hosts_csv() -> None:
    hosts = parse_allowed_hosts("YouTube.COM, tiktok.com, ")
    assert hosts == frozenset({"youtube.com", "tiktok.com"})


def test_parse_allowed_hosts_json_array() -> None:
    hosts = parse_allowed_hosts('["Twitter.com","X.COM"]')
    assert hosts == frozenset({"twitter.com", "x.com"})


def test_parse_allowed_hosts_wildcard() -> None:
    assert parse_allowed_hosts("*") == frozenset()


def test_get_settings_reads_bot_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIX_BOT_TOKEN", "  abc:def  ")
    clear_settings_cache()
    s = get_settings()
    assert s.BOT_TOKEN == "abc:def"


def test_download_log_every_progress_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIX_DOWNLOAD_LOG_EVERY_PROGRESS", "true")
    s = Settings()
    assert s.DOWNLOAD_LOG_EVERY_PROGRESS is True


def test_allowed_hosts_csv_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIX_ALLOWED_HOSTS", "example.org,WWW.EXAMPLE.org")
    s = Settings()
    assert s.ALLOWED_HOSTS == frozenset({"example.org", "www.example.org"})


def test_allowed_hosts_blank_env_falls_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIX_ALLOWED_HOSTS", "")
    s = Settings()
    assert "youtube.com" in s.ALLOWED_HOSTS
    assert len(s.ALLOWED_HOSTS) >= 10


def test_parse_hosts_json_empty_allows_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIX_ALLOWED_HOSTS", "[]")
    s = Settings()
    assert len(s.ALLOWED_HOSTS) == 0
