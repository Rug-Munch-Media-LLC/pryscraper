"""Shared helpers for deal-aggregator coupon scraping.

Configuration, HTTP fetching with bounded backoff, text/price coercion
helpers, and the thread-safe per-source blocked-state registry.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import threading
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

# ── endpoints & configuration ──────────────────────────────────────────
_SLICKDEALS_SEARCH_URL = "https://slickdeals.net/newsearch.php"
_SLICKDEALS_STORE_URL = "https://slickdeals.net/store/{store}/"
_RETAILMENOT_SEARCH_URL = "https://www.retailmenot.com/s/{q}"
_RETAILMENOT_STORE_URL = "https://www.retailmenot.com/view/{store}"

_MAX_LIMIT = 100

_TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=8.0)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Backoff tuning (tests monkeypatch these to 0 for speed).
RETRY_BASE = 0.5
MAX_BACKOFF = 2.0
MAX_RETRIES = 1

# Anti-bot challenge markers observed across Cloudflare / Datadome / PX.
_BLOCK_MARKERS = (
    "captcha",
    "cf-chl",
    "cf-browser-verification",
    "cloudflare",
    "px-captcha",
    "attention required",
    "access denied",
    "are you a human",
    "verify you are human",
    "datadome",
)

# Per-source blocked state from the most recent call (thread-safe).
_BLOCKED: dict[str, bool] = {}
_LOCK = threading.RLock()


# ── low-level helpers ──────────────────────────────────────────────────


def _clamp_limit(limit: Any) -> int:
    """Coerce ``limit`` to an int within [1, _MAX_LIMIT]; default 20."""
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = 20
    return max(1, min(value, _MAX_LIMIT))


def _url_quote(text: str) -> str:
    return quote(text, safe="")


def _to_float(value: Any) -> float | None:
    """Coerce a JSON/text value to float; None when not numeric."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _money_float(raw: Any) -> float | None:
    """Parse a price-ish string like ``"$1,234.56"`` / ``"1 234,56"``."""
    if isinstance(raw, (int, float)):
        return _to_float(raw)
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    text = re.sub(r"[^\d.,\-]", "", text)
    if not text or text in {"-", "."}:
        return None
    if "," in text and "." in text:
        # "$1,234.56" → strip the thousands separator, keep the decimals.
        if text.rfind(",") < text.rfind("."):
            text = text.replace(",", "")
        else:
            text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _percent_discount(price: float | None, original: float | None) -> float | None:
    """Percent saved between a current price and its original price."""
    if price is None or original is None or original <= 0 or price <= 0:
        return None
    return round((1.0 - price / original) * 100.0, 1)


def _parse_text_discount(price: float | None, original: float | None, text: str) -> float | None:
    """Fall back to a ``% off`` / ``$X off`` literal found in deal text."""
    if _percent_discount(price, original) is not None:
        return _percent_discount(price, original)
    pct = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if pct:
        return float(pct.group(1))
    off = re.search(r"\$\s*(\d+(?:\.\d+)?)\s*off", text, re.IGNORECASE)
    if off and price is not None and price > 0:
        return round(float(off.group(1)) / price * 100.0, 1)
    return None


def _clean_text(raw: Any) -> str:
    """Strip tags/whitespace from scraped text."""
    text = re.sub(r"<[^>]+>", " ", str(raw or ""))
    return re.sub(r"\s+", " ", text).strip()


def _deal_id(source: str, url: str, title: str) -> str:
    """Deterministic deal id from source + url (fallback: title hash)."""
    seed = url or title or source
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _is_blocked_html(raw: str) -> bool:
    """Heuristic: does this page look like an anti-bot challenge page?"""
    lowered = (raw or "").lower()
    return any(marker in lowered for marker in _BLOCK_MARKERS)


async def _sleep_backoff(attempt: int) -> None:
    """Sleep with capped exponential backoff (knobs are test-overridable)."""
    if attempt <= 0 or RETRY_BASE <= 0 or MAX_BACKOFF <= 0:
        return
    await asyncio.sleep(min(MAX_BACKOFF, RETRY_BASE * (2**attempt)))


async def _fetch(url: str, params: dict[str, str] | None = None) -> str:
    """GET a URL with bounded backoff retries; never raises ('' on failure)."""
    last_error = ""
    for attempt in range(MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
            ) as client:
                resp = await client.get(url, params=params)
            if resp.status_code == 429:
                last_error = "HTTP 429 (rate limited)"
                await _sleep_backoff(attempt)
                continue
            if resp.status_code >= 400:
                last_error = f"HTTP {resp.status_code}"
                await _sleep_backoff(attempt)
                continue
            return resp.text
        except (httpx.HTTPError, OSError) as exc:
            last_error = str(exc)[:120]
            await _sleep_backoff(attempt)
    logger.warning("deals_fetch_failed", extra={"url": url[:120], "error": last_error})
    return ""


def _dedupe_deals(records: list[dict[str, Any]], bounded: int) -> list[dict[str, Any]]:
    """Dedupe by url (then id) and cap at ``bounded``."""
    seen_urls: set[str] = set()
    seen_ids: set[str] = set()
    out: list[dict[str, Any]] = []
    for record in records:
        url = str(record.get("url") or "")
        deal_id = str(record.get("id") or "")
        if url and url in seen_urls:
            continue
        if deal_id in seen_ids:
            continue
        if url:
            seen_urls.add(url)
        seen_ids.add(deal_id)
        out.append(record)
        if len(out) >= bounded:
            break
    return out


def blocked_sources() -> list[str]:
    """Sources that looked anti-bot-blocked on the most recent call.

    Sync helper for observability (deal bots can surface this in their
    status). Cleared at the start of every search/store call.
    """
    with _LOCK:
        return [source for source, blocked in _BLOCKED.items() if blocked]


def _mark_blocked(source: str, blocked: bool) -> None:
    with _LOCK:
        _BLOCKED[source] = blocked
