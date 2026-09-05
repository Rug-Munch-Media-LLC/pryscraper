"""Polymarket prediction-market data — Gamma public API.

Pulls live markets from the Polymarket Gamma API
(``https://gamma-api.polymarket.com``) — no API key, no quota:

* ``GET /markets`` — flat market list (question, outcomes, prices,
  volume, liquidity, end date, category).
* ``GET /events`` — event-grouped markets (each event nests its
  markets); used as a fallback when the flat feed is unavailable.

Contract
--------
* :func:`get_polymarket_markets` — async, never raises, returns a
  ``list`` (``[]`` on failure). One normalized record per market.
* :func:`get_polymarket_market` — async, never raises, returns a
  ``dict`` (``{}`` on failure). Single-market lookup by id or slug.

Record shape: ``{market_id, source, question, category, outcomes,
yes_price, no_price, volume, liquidity, resolution_date, url,
active, last_update}``. Prices are 0-1 probabilities (Gamma returns
them as strings); ``outcomes`` is ``[{name, price}]``.

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

import json
import logging
import sys
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from pry.engine.retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

# ── Transport ──────────────────────────────────────────────────────────
GAMMA_BASE = "https://gamma-api.polymarket.com"
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
            raise ValueError("polymarket payload is not an object or array")
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
    """Best-effort float coercion (Gamma prices arrive as strings)."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_jsonish(value: Any) -> list[Any]:
    """Gamma encodes ``outcomes``/``outcomePrices`` as JSON strings."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_market(raw: dict[str, Any]) -> dict[str, Any]:
    """Map one Gamma market object to the unified prediction-market shape."""
    outcomes_raw = _parse_jsonish(raw.get("outcomes"))
    prices_raw = _parse_jsonish(raw.get("outcomePrices"))
    outcomes: list[dict[str, Any]] = []
    for index, name in enumerate(outcomes_raw):
        price = _to_float(prices_raw[index]) if index < len(prices_raw) else None
        outcomes.append({"name": _as_text(name), "price": price})
    yes_price = next(
        (o["price"] for o in outcomes if o["name"].lower() in {"yes", "up"}),
        None,
    )
    no_price = next(
        (o["price"] for o in outcomes if o["name"].lower() in {"no", "down"}),
        None,
    )
    market_id = _as_text(raw.get("id")) or _as_text(raw.get("slug"))
    slug = _as_text(raw.get("slug"))
    return {
        "market_id": market_id,
        "source": "polymarket",
        "question": _as_text(raw.get("question")),
        "category": _as_text(raw.get("category")).lower() or None,
        "outcomes": outcomes,
        "yes_price": yes_price,
        "no_price": no_price,
        "volume": _to_float(raw.get("volume")),
        "liquidity": _to_float(raw.get("liquidity")),
        "resolution_date": _as_text(raw.get("endDate")) or None,
        "url": f"https://polymarket.com/market/{slug}" if slug else None,
        "active": bool(raw.get("active", True)) and not bool(raw.get("closed", False)),
        "last_update": _now_iso(),
    }


# ── Public API ─────────────────────────────────────────────────────────
async def get_polymarket_markets(
    category: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Fetch live Polymarket markets via the Gamma API.

    Args:
        category: Optional category filter applied client-side against the
            market question/category text (e.g. ``"politics"``). ``None``
            or ``"all"`` matches everything.
        limit: Max records to return (1-100).

    Returns:
        A list of normalized market records (see module docstring).
        ``[]`` on failure. Never raises.
    """
    try:
        return await _get_polymarket_markets(category, limit)
    except Exception:
        logger.exception(
            "polymarket_markets_crashed",
            extra={"category": category, "limit": limit},
        )
        return []


async def _get_polymarket_markets(category: str | None, limit: int) -> list[dict[str, Any]]:
    clamped = max(1, min(int(limit), 100))
    params = {"limit": str(clamped * 2), "closed": "false", "active": "true"}
    payload = await _fetch_json(f"{GAMMA_BASE}/markets", params)
    raws: list[dict[str, Any]] = []
    if isinstance(payload, list):
        raws = [raw for raw in payload if isinstance(raw, dict)]
    if not raws:
        # Fallback: the /events feed nests markets inside events.
        raws = await _markets_from_events(clamped * 2)
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


async def _markets_from_events(limit: int) -> list[dict[str, Any]]:
    """Flatten ``/events`` payloads into market objects (fallback path)."""
    payload = await _fetch_json(
        f"{GAMMA_BASE}/events", {"limit": str(max(1, limit // 2)), "closed": "false"}
    )
    if not isinstance(payload, list):
        return []
    raws: list[dict[str, Any]] = []
    for event in payload:
        if not isinstance(event, dict):
            continue
        markets = event.get("markets")
        if isinstance(markets, list):
            raws.extend(raw for raw in markets if isinstance(raw, dict))
    return raws[:limit]


async def get_polymarket_market(market_id: str) -> dict[str, Any]:
    """Fetch a single Polymarket market by id or slug.

    Args:
        market_id: Gamma market id or slug (e.g. ``"will-bitcoin-hit-100k"``).

    Returns:
        A normalized market record (see module docstring) or ``{}`` on
        failure (unknown market, network error). Never raises.
    """
    try:
        return await _get_polymarket_market(market_id)
    except Exception:
        logger.exception(
            "polymarket_market_crashed",
            extra={"market_id": market_id},
        )
        return {}


async def _get_polymarket_market(market_id: str) -> dict[str, Any]:
    target = (market_id or "").strip()
    if not target:
        return {}
    # Try by-id first, then by-slug (Gamma exposes both lookups).
    for param_name in ("id", "slug"):
        payload = await _fetch_json(f"{GAMMA_BASE}/markets", {param_name: target})
        if isinstance(payload, list):
            for raw in payload:
                if isinstance(raw, dict) and (
                    _as_text(raw.get("id")) == target or _as_text(raw.get("slug")) == target
                ):
                    return _normalize_market(raw)
        elif isinstance(payload, dict) and payload.get("id"):
            return _normalize_market(payload)
    return {}
