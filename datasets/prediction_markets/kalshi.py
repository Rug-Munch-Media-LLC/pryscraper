"""Kalshi prediction-market data — public trade API v2.

Pulls live markets from the Kalshi public API
(``https://api.elections.kalshi.com/trade-api/v2``) — no API key for
public market data:

* ``GET /markets`` — paginated market list (title, yes/no prices,
  volume, open interest, close time, category).

Contract
--------
* :func:`get_kalshi_markets` — async, never raises, returns a ``list``
  (``[]`` on failure). One normalized record per market.
* :func:`get_kalshi_market` — async, never raises, returns a ``dict``
  (``{}`` on failure). Single-market lookup by ticker.

Record shape: ``{market_id, source, question, category, outcomes,
yes_price, no_price, volume, liquidity, resolution_date, url, active,
last_update}``. Kalshi quotes cents (0-100); prices are normalized to
0-1 probabilities to match the Polymarket records.

Caching: raw upstream responses are cached in-memory for 10 seconds
(bots poll fast), bypassed while an HTTP mock (respx) is active.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
import sys
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from pry.engine.retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

# ── Transport ──────────────────────────────────────────────────────────
KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
_TIMEOUT = httpx.Timeout(10.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=1,
    base_delay=0.1,
    max_delay=0.4,
    retryable_exceptions=(httpx.HTTPError,),
)
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; pryscraper-prediction/1.0; "
    "+https://git.rugmunch.io/RugMunchMedia/pryscraper)",
    "Accept": "application/json",
}

_CACHE_TTL = 10.0
_http_cache: dict[tuple[Any, ...], tuple[float, Any]] = {}


def _monotonic() -> float:
    """Injectable clock for cache expiry (tests control time)."""
    return time.monotonic()


def _cache_enabled() -> bool:
    """Return False while an HTTP mock (respx) is active."""
    respx_mod = sys.modules.get("respx")
    if respx_mod is None:
        return True
    return not bool(getattr(respx_mod, "routes", []))


def _cache_key(url: str, params: dict[str, str] | None) -> tuple[Any, ...]:
    """Cache key = URL + sorted query params."""
    return (url, tuple(sorted((params or {}).items())))


def _clear_cache() -> None:
    """Drop all cached upstream responses (exposed for tests/tuning)."""
    _http_cache.clear()


async def _fetch_json(
    url: str, params: dict[str, str] | None = None
) -> dict[str, Any] | list[Any] | None:
    """GET ``url`` (cached for :data:`_CACHE_TTL` seconds) and parse JSON.

    Returns the parsed object/array, or ``None`` on failure. Never raises.
    """
    key = _cache_key(url, params)
    if _cache_enabled():
        entry = _http_cache.get(key)
        if entry is not None:
            cached_at, payload = entry
            if _monotonic() - cached_at < _CACHE_TTL:
                return payload
            _http_cache.pop(key, None)
    payload = await _fetch_uncached(url, params)
    if payload is not None and _cache_enabled():
        _http_cache[key] = (_monotonic(), payload)
    return payload


async def _fetch_uncached(
    url: str, params: dict[str, str] | None = None
) -> dict[str, Any] | list[Any] | None:
    """Perform the actual HTTP GET with retry/backoff (no caching)."""

    async def _one() -> dict[str, Any] | list[Any]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, (dict, list)):
            raise ValueError("kalshi payload is not an object or array")
        return payload

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


# ── Normalization helpers ─────────────────────────────────────────────
def _as_text(value: Any) -> str:
    """Coerce an upstream scalar to a trimmed string (``""`` for None)."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _to_float(value: Any) -> float | None:
    """Best-effort float coercion."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _cents_to_prob(value: Any) -> float | None:
    """Kalshi quotes cents (0-100); normalize to a 0-1 probability."""
    number = _to_float(value)
    if number is None:
        return None
    return number / 100.0 if number > 1.0 else number


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_market(raw: dict[str, Any]) -> dict[str, Any]:
    """Map one Kalshi market object to the unified prediction-market shape."""
    ticker = _as_text(raw.get("ticker"))
    yes_price = _cents_to_prob(raw.get("yes_bid") or raw.get("last_price"))
    no_price = _cents_to_prob(raw.get("no_bid"))
    if no_price is None and yes_price is not None:
        no_price = round(1.0 - yes_price, 6)
    return {
        "market_id": ticker,
        "source": "kalshi",
        "question": _as_text(raw.get("title")) or _as_text(raw.get("yes_sub_title")),
        "category": _as_text(raw.get("category")).lower() or None,
        "outcomes": [
            {"name": "Yes", "price": yes_price},
            {"name": "No", "price": no_price},
        ],
        "yes_price": yes_price,
        "no_price": no_price,
        "volume": _to_float(raw.get("volume")),
        "liquidity": _to_float(raw.get("open_interest")),
        "resolution_date": _as_text(raw.get("close_time")) or None,
        "url": f"https://kalshi.com/markets/{ticker.lower()}" if ticker else None,
        "active": _as_text(raw.get("status")).lower() in {"active", "open", ""},
        "last_update": _now_iso(),
    }


# ── Public API ─────────────────────────────────────────────────────────
async def get_kalshi_markets(
    category: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Fetch live Kalshi markets via the public trade API.

    Args:
        category: Optional category filter applied client-side against the
            market title/category text (e.g. ``"sports"``). ``None`` or
            ``"all"`` matches everything.
        limit: Max records to return (1-100).

    Returns:
        A list of normalized market records (see module docstring).
        ``[]`` on failure. Never raises.
    """
    try:
        return await _get_kalshi_markets(category, limit)
    except Exception:
        logger.exception(
            "kalshi_markets_crashed",
            extra={"category": category, "limit": limit},
        )
        return []


async def _get_kalshi_markets(category: str | None, limit: int) -> list[dict[str, Any]]:
    clamped = max(1, min(int(limit), 100))
    params = {"limit": str(clamped * 2), "status": "open"}
    payload = await _fetch_json(f"{KALSHI_BASE}/markets", params)
    raws: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        markets = payload.get("markets")
        if isinstance(markets, list):
            raws = [raw for raw in markets if isinstance(raw, dict)]
    records = [_normalize_market(raw) for raw in raws]
    records = [record for record in records if record["market_id"]]
    if category and category.lower() != "all":
        needle = category.lower()
        records = [
            record
            for record in records
            if needle in str(record.get("category") or "").lower()
            or needle in str(record.get("question") or "").lower()
        ]
    records.sort(key=lambda record: float(record.get("volume") or 0.0), reverse=True)
    return records[:clamped]


async def get_kalshi_market(market_id: str) -> dict[str, Any]:
    """Fetch a single Kalshi market by ticker.

    Args:
        market_id: Kalshi market ticker (e.g. ``"KXNBAMVP-26"``).

    Returns:
        A normalized market record (see module docstring) or ``{}`` on
        failure (unknown market, network error). Never raises.
    """
    try:
        return await _get_kalshi_market(market_id)
    except Exception:
        logger.exception(
            "kalshi_market_crashed",
            extra={"market_id": market_id},
        )
        return {}


async def _get_kalshi_market(market_id: str) -> dict[str, Any]:
    target = (market_id or "").strip()
    if not target:
        return {}
    payload = await _fetch_json(f"{KALSHI_BASE}/markets/{target}")
    if isinstance(payload, dict) and payload.get("ticker"):
        return _normalize_market(payload)
    # Some deployments wrap the market in a "market" key.
    if isinstance(payload, dict) and isinstance(payload.get("market"), dict):
        return _normalize_market(payload["market"])
    return {}
