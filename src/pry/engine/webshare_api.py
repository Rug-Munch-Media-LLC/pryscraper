"""Pry — Webshare proxy-list API client (paginated; one job: fetch rows).

The API key is read from an operator-supplied env file (``PRY_WEBSHARE_KEY_FILE``,
default ``~/.config/pry/webshare.env``) and falls back to ``WEBSHARE_API_KEY``.
It is never logged.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

API_URL = "https://proxy.webshare.io/api/v2/proxy/list/"
KEY_FILE = os.getenv("PRY_WEBSHARE_KEY_FILE", str(Path("~/.config/pry/webshare.env").expanduser()))
KEY_ENV = "WEBSHARE_API_KEY"
PAGE_SIZE, MAX_PAGES = 100, 10


def api_key() -> str:
    """API key, file-first and env-last. Never logged."""
    try:
        lines = Path(KEY_FILE).read_text(encoding="utf-8").splitlines()
    except OSError:
        logger.debug("best-effort fallback", exc_info=True)
        lines = []
    for line in lines:
        if line.strip().startswith(f"{KEY_ENV}="):
            value = line.split("=", 1)[1].strip().strip("\"'")
            if value:
                return value
    return os.getenv(KEY_ENV, "").strip()


def fetch_proxies(key: str, timeout_s: float) -> list[dict]:
    """Every valid ``mode=direct`` proxy row, paginating to completion."""
    out: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        resp = httpx.get(
            API_URL,
            params={"mode": "direct", "page": page, "page_size": PAGE_SIZE},
            headers={"Authorization": f"Token {key}"},
            timeout=httpx.Timeout(timeout_s),
        )
        resp.raise_for_status()
        data = resp.json() or {}
        rows = [r for r in (data.get("results") or []) if r.get("valid", True)]
        out.extend(rows)
        if len(rows) < PAGE_SIZE or len(out) >= int(data.get("count") or 0):
            break
    return out
