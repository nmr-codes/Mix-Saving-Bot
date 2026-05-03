# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN groupadd --system --gid 10001 mixbot \
    && useradd --system --uid 10001 --gid mixbot --home /app --shell /usr/sbin/nologin mixbot

# Dependency layer (invalidates less often than app code).
COPY requirements.txt pyproject.toml README.md ./

RUN pip install --no-cache-dir -r requirements.txt

# Application + packaged install (console script ``mix-saving-bot`` from ``pyproject.toml``).
COPY . .

RUN pip install --no-cache-dir --no-deps . \
    && mkdir -p /data/cache \
    && chown -R mixbot:mixbot /app /data/cache

ENV MIX_CACHE_ROOT_DIR=/data/cache

USER mixbot

VOLUME ["/data/cache"]

# Import smoke only — does not call Telegram (suitable for Compose / Railway health probes).
HEALTHCHECK --interval=45s --timeout=15s --start-period=40s --retries=4 \
    CMD python -c "import aiogram, yt_dlp; import bot.app, core.settings, run_bot"

CMD ["mix-saving-bot"]
