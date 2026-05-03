# Deploying mix-saving-bot

This project runs the Telegram UI as **`mix-saving-bot`** (or `python run_bot.py`) inside Docker. The queue stack alone can be exercised with `python -m services` where applicable.

---

## 1. Local (Docker Compose)

### Prereqs

- Docker Engine + Docker Compose v2
- A BotFather token (`MIX_BOT_TOKEN`)

### Steps

1. `cp .env.example .env` and set `MIX_BOT_TOKEN`.
2. Optional: tune `MIX_MAX_CONCURRENT_DOWNLOADS`, `mem_limit` in `docker-compose.yml`, or cache path `MIX_CACHE_ROOT_DIR`.
3. Build and run:

   ```bash
   docker compose up -d --build
   ```

4. Follow logs:

   ```bash
   docker compose logs -f bot
   ```

### Optional Redis service

Other modules can use Redis when configured. Start the sidecar when you wire `MIX_REDIS_URL`:

```bash
docker compose --profile redis up -d redis bot
```

---

## 2. VPS (same image, production habits)

1. Install Docker (official convenience script or distro packages).
2. Clone the repo on the server **or** pull a registry image you built in CI.
3. Copy `.env.example` → `.env` with secrets (`MIX_BOT_TOKEN`, optional `MIX_SAVING_API_BASE`).
4. Use Compose with bounded resources (example already sets `restart: unless-stopped`, volume `bot_cache`, and `mem_limit`):

   ```bash
   docker compose up -d --build
   ```

5. Prefer a firewall that allows outbound HTTPS (Telegram, CDNs); **no inbound port** is required for long‑polling bots.
6. **TLS / webhooks**: this image uses **long polling**. Switching to webhooks requires a public HTTPS endpoint and code changes (`setWebhook`) unless you extend the app accordingly.

---

## 3. Railway

1. Create a Railway project connected to this repository (or deploy a pushed image).
2. Use Dockerfile build (Railway detects `Dockerfile` in the repo root).
3. In **Variables**, add every key from `.env.example` your deployment needs (`MIX_BOT_TOKEN` minimum). Map `MIX_CACHE_ROOT_DIR` to a writable path Railway provides **or** use `/data/cache` and attach a **volume** mapped to `/data/cache` for durability.
4. Use a **persistent volume** if you rely on dedupe index files under `MIX_CACHE_ROOT_DIR`; ephemeral disks lose cache hints after deploys without a volume.
5. Railway free tiers may sleep; Telegram polling expects a continuously running worker. Choose an always‑on tier for serious production workloads.
6. **Healthcheck**: the Dockerfile probes Python imports (`HEALTHCHECK`); it does not dial Telegram so Railway health is not falsely red when Telegram is briefly unavailable.

---

## Edge cases & mitigation

### Container exits or crashes

- Compose sets `restart: unless-stopped` so Docker restarts the process automatically.
- Keep `MIX_HIGH_WATER_QUEUE_DEPTH` and `MIX_MAX_CONCURRENT_DOWNLOADS` aligned so traffic spikes do not thrash FFmpeg or memory.

### Memory pressure (OOM)

- Reduce `MAX_CONCURRENT_DOWNLOADS` or relax queue depth before raising Docker `mem_limit`.
- yt‑dlp + FFmpeg can spike dramatically during merges; oversized videos increase peak RSS.

### Disk / cache overflow

- Persist `bot_cache` via a Docker volume so space is isolated from root FS.
- `MIX_MAX_OUTPUT_BYTES` rejects giant outputs before Telegram upload attempts.
- The dedupe index (`dedupe_index.jsonl`) grows gradually; prune it during maintenance windows if rotation is required.

### Network loss / flaky CDNs

- Local mode uses yt‑dlp fragment retries/timeouts configured in `services/downloader.py`.
- Remote downloader mode honours `MIX_BACKEND_POLL_INTERVAL` and `MIX_BACKEND_JOB_TIMEOUT_SEC` in `services/remote_backend.py`.

### Telegram upload limits

If the file exceeds the Bot API size cap for your account, uploads fail visibly in chat. Adjust `MIX_TELEGRAM_MAX_UPLOAD_BYTES` to reflect your provider limits before attempting large sends.

---

## Modes recap

| Mode | When | Configure |
| --- | --- | --- |
| **Local yt-dlp** | Default Docker run | Omit `MIX_SAVING_*` downloader API URLs; FFmpeg is bundled in the image. |
| **Remote downloader API** | Split workers / SaaS downloader | Set `MIX_SAVING_API_BASE` (alias `MIX_SAVING_BACKEND_URL`). |
