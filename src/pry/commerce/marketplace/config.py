"""Marketplace HTTP configuration — timeouts, UA pool, env-driven knobs.

Shared by the marketplace transport modules. All values are free-tier
friendly and read from the environment at call time (no secrets).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import os
import random

import httpx

# SystemRandom so UA rotation / jitter is not predictable.
_RNG = random.SystemRandom()

# ── HTTP configuration ─────────────────────────────────────────────────
HTTP_TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=8.0)
ROBOTS_TIMEOUT = httpx.Timeout(connect=4.0, read=6.0, write=6.0, pool=4.0)
RETRY_BASE = 0.5  # seconds — exponential backoff base
MAX_BACKOFF = 3.0  # seconds — backoff cap

# Realistic desktop + mobile user agents for rotation.
_USER_AGENTS: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
)


def _rotate_ua() -> str:
    """Pick a user agent: env override, else a random one from the pool."""
    override = os.getenv("PRY_MARKETPLACE_USER_AGENT", "").strip()
    if override:
        return override
    return _RNG.choice(_USER_AGENTS)


def _http_retries() -> int:
    """Retry count per request from env (default 2; min 1)."""
    try:
        return max(1, int(os.getenv("PRY_MARKETPLACE_HTTP_RETRIES", "2")))
    except ValueError:
        return 2


def _honor_robots() -> bool:
    return os.getenv("PRY_MARKETPLACE_HONOR_ROBOTS", "1").lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
