#!/usr/bin/env python3
"""Run the Telegram interface and downloader workers (single process by default)."""

from __future__ import annotations

import asyncio

from run_bot import main

if __name__ == "__main__":
    asyncio.run(main())
