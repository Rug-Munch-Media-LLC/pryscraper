"""Pry — SERP scrape configuration: endpoint, headers, timeouts, retry budget."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import httpx

_SERP_URL = "https://www.google.com/search"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=8.0)

# Backoff tuning (tests patch RETRY_BASE/MAX_BACKOFF on the fetch module).
RETRY_BASE = 0.5
MAX_BACKOFF = 2.0
MAX_RETRIES = 2

_MAX_NUM = 100

# A usable SERP is a real result page, not a consent/block interstitial shell.
_MIN_USABLE_SERP_BYTES = 20000
