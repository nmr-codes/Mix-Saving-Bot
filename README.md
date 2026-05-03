# mix-saving-bot

Telegram bot that queues media download jobs, runs **yt-dlp–backed workers**, caches blobs on disk, and replies with finished files. The stack is fully **async** (`asyncio` + **aiogram 3**).

---

## What you need installed

| Requirement | Why |
|-------------|-----|
| **Python 3.11+** | Matches `requires-python` in `pyproject.toml`. |
| **ffmpeg** | Required for audio extraction / container merges (unless you only fetch remuxed streams). |
| **Redis** (optional) | Only if `MIX_QUEUE_BACKEND=redis`. |

The Python package **depends on `yt-dlp`**, which ships with the project (`pyproject.toml`). You can still point to a system **ffmpeg** explicitly with `MIX_SAVING_FFMPEG_LOCATION`.

---

## Quick install

From the repository root:

```bash
python3.11 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -e .
```

Install dev tools (pytest):

```bash
pip install -e ".[dev]"
```

---

## Configure environment variables

1. Copy the template:
   ```bash
   cp .env.example .env
   ```
2. Edit `.env` — each key is documented inline in `.env.example`.
3. **`MIX_BOT_TOKEN` is mandatory** for the live Telegram client. Create a bot with [@BotFather](https://t.me/BotFather) and paste the token.

### How settings are loaded

- `core/settings.py` uses **Pydantic Settings** with prefix `MIX_` and automatically reads `.env`.
- Host allow-list quirks:
  - **Comma-separated** values work (`youtube.com,youtu.be`).
  - JSON arrays work (`["youtube.com"]`).
  - `*` disables host filtering (**dangerous** — use only in trusted lab environments).
  - **Blank / unset `MIX_ALLOWED_HOSTS`** → built-in curated list.
  - A JSON payload of **`[]`** (empty array) ⇒ *no hostname filtering* — only use deliberately.

Redis queue mode requires `MIX_REDIS_URL` when `MIX_QUEUE_BACKEND=redis`.

---

## Run the bot + workers

`run_bot.py` starts:

1. aiogram **Dispatcher** (Telegram updates, inline keyboard flow for video/audio).
2. **Background consumer** (`services.worker_runner.run_worker_loop`) attached to the queue.

### Option A — packaged console script

```bash
mix-saving-bot
```

### Option B — module / file entrypoints

```bash
python run_bot.py
python bot.py                # thin wrapper around `run_bot.main()`
```

Press `Ctrl+C` to stop; shutdown closes the queue producer/consumer and the aiogram HTTP session.

---

## Development workflow

```bash
pytest                          # run the full suite (36+ tests)
pytest tests/test_sanitize.py   # focus on URL validation
```

Tests automatically:

- clear the cached `get_settings()` singleton between cases, and
- reset in-process metrics.

---

## Project map

| Path | Role |
|------|------|
| `bot/` | aiogram routers, middleware (logging + rate limit), notifier, pending inline-keyboard state. |
| `core/` | Settings, contracts, logging, lightweight metrics. |
| `downloader/` | yt-dlp integration + sanitization helpers. |
| `services/` | Job repository, memory/redis queues, cache store, worker loop, optional HTTP bridge (`remote_backend.py`). |
| `run_bot.py` | Process composition (bot + queue + workers). |
| `tests/` | Pytest coverage for settings, sanitization, jobs, queues, cache, middleware, notifier, dispatcher smoke. |

---

## Operational tips

- **Large Telegram uploads:** `bot/notifier.py` caps bot uploads around **49 MiB** (Telegram Bot API practical limit for many accounts). Shorter clips or **audio** mode may be required.
- **Cookies / geo-blocked sources:** set `MIX_SAVING_YTDLP_COOKIESFILE` to a Netscape cookie file path (see `.env.example`).
- **Custom yt-dlp flags:** point `MIX_YTDLP_CONFIG_PATH` or `MIX_SAVING_YTDLP_CONFIG` at a config file.
- **Horizontal scaling:** switch to `MIX_QUEUE_BACKEND=redis`, run multiple worker processes with distinct `MIX_REDIS_QUEUE_CONSUMER_NAME` values, and keep a shared `MIX_CACHE_ROOT_DIR` (NFS / object store mount) if you want cross-host cache reuse.

---

## HTTP job API (optional)

`services/remote_backend.py` implements a generic REST client for external download orchestration. The production `run_bot.py` path uses **in-process yt-dlp** instead, but the module is available for custom wiring; see the `MIX_SAVING_API_BASE` / `MIX_BACKEND_*` keys in `.env.example`.

---

## License / support

This repository is an application template. Inspect `pyproject.toml` for dependency pins and adapt logging or metrics (`core/observability.py`) to your platform.
