"""Multi-source sports odds fetchers + cross-source merge for Pry.

Extends the odds engine (:mod:`sports_data.odds`, The Odds API + ESPN) with
three additional free sources so a single dead/blocked/quota-bound source
never blanks the odds feed:

* **OddsPortal** (``www.oddsportal.com``) — consumer odds-comparison site
  with 80+ bookmakers across every sport (scrape; blocks are detected and
  flagged honestly, never silently treated as "no odds").
* **Bovada** (``www.bovada.lv``) — offshore book with a public JSON odds
  feed. Returns h2h, spreads and totals as decimal odds.
* **BetOnline** (``www.betonline.ag``) — offshore book; no public JSON API,
  so this fetcher parses the sportsbook listing pages (best-effort).

Contract
--------
* Every ``fetch_*`` is async and never raises — it returns ``[]`` on any
  failure (network, block, malformed payload, unsupported sport). One source
  being down never affects the others.
* Every record follows the canonical odds schema from
  :mod:`sports_data.odds` and is tagged with its origin ``source``.
* :data:`SOURCES` is the static registry (kind, base url, confidence,
  markets, notes); :func:`source_status` / :func:`available_sources` add the
  live per-source availability seen by the last fetch.
* :func:`merge_odds` dedupes records across sources by (event, market, book),
  prefers sharp books (Pinnacle) on conflict, and keeps the winning record's
  ``source`` tag.

Free-API terms: OddsPortal (consumer site, no API), Bovada / BetOnline
(unofficial public feeds — scrape politely, expect geo-blocks and layout
drift).

Shared helpers/registries live in :mod:`sports_data.sources_common`, the
merge in :mod:`sports_data.sources_merge`, and the per-source fetchers in
``sources_oddsportal`` / ``sources_bovada`` / ``sources_betonline``; this
module re-exports them so the ``sports_data.sources`` surface is unchanged.

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
import random
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from datasets.sports_data.sources_betonline import (  # re-exported surface
    _container_text as _container_text,
    _parse_betonline_embedded_json as _parse_betonline_embedded_json,
    _parse_betonline_html as _parse_betonline_html,
    _team_names_from_container as _team_names_from_container,
    fetch_betonline as fetch_betonline,
)
from datasets.sports_data.sources_bovada import (  # re-exported surface
    _bovada_handicap as _bovada_handicap,
    _bovada_price as _bovada_price,
    _bovada_side as _bovada_side,
    _parse_bovada_event as _parse_bovada_event,
    fetch_bovada as fetch_bovada,
)
from datasets.sports_data.sources_common import (  # re-exported surface
    _BETONLINE_SPORTS as _BETONLINE_SPORTS,
    _BLOCK_MARKERS as _BLOCK_MARKERS,
    _BOVADA_SPORTS as _BOVADA_SPORTS,
    _ODDSPORTAL_SPORTS as _ODDSPORTAL_SPORTS,
    _SPORTS as _SPORTS,
    _american_to_decimal as _american_to_decimal,
    _as_text as _as_text,
    _canonical_book as _canonical_book,
    _classes as _classes,
    _event_id_matches as _event_id_matches,
    _event_label as _event_label,
    _from_html as _from_html,
    _looks_blocked as _looks_blocked,
    _normalize_label as _normalize_label,
    _normalize_team as _normalize_team,
    _record as _record,
    _record_teams as _record_teams,
    _resolve_sports as _resolve_sports,
    _split_label as _split_label,
    _teams_contain as _teams_contain,
    _to_float as _to_float,
    event_matches as event_matches,
    same_event as same_event,
    source_supports as source_supports,
)
from datasets.sports_data.sources_merge import (  # re-exported surface
    _conflicts as _conflicts,
    _priority_key as _priority_key,
    _source_rank as _source_rank,
    _ts_float as _ts_float,
    merge_odds as merge_odds,
)
from datasets.sports_data.sources_oddsportal import (  # re-exported surface
    _cell_to_number as _cell_to_number,
    _parse_oddsportal_listing as _parse_oddsportal_listing,
    _parse_oddsportal_match as _parse_oddsportal_match,
    _slug_pair as _slug_pair,
    _slug_to_name as _slug_to_name,
    fetch_oddsportal as fetch_oddsportal,
)
from pry.engine.retry import RetryConfig, async_retry

# SystemRandom: crypto-grade entropy so stealth jitter is not predictable.
_RNG = random.SystemRandom()

logger = logging.getLogger(__name__)

# ── Source registry ─────────────────────────────────────────────────────
# Canonical source names (the order also defines conflict precedence in
# merge_odds: earlier sources win ties against equally sharp books).
SOURCE_NAMES: tuple[str, ...] = (
    "the_odds_api",
    "espn",
    "oddsportal",
    "bovada",
    "betonline",
)
SOURCE_PRIORITY: tuple[str, ...] = SOURCE_NAMES

# Static per-source metadata. Live availability (reachable/blocked/latency)
# is tracked separately and merged by source_status()/available_sources().
# Confidence is a 0..1 estimate of how reliably the source yields clean odds
# today — it deliberately drops for the scrape-based sources whose markup is
# not a stable API contract. The registry itself is data-driven (JSON).
_DATA_DIR = Path(__file__).resolve().parent / "data"


def _load_json(name: str) -> Any:
    with (_DATA_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


SOURCES: dict[str, dict[str, Any]] = _load_json("sources.json")

# ── Live availability tracking ──────────────────────────────────────────
_HEALTH: dict[str, dict[str, Any]] = {
    name: {
        "reachable": True,
        "blocked": False,
        "last_checked": None,
        "latency_ms": None,
        "error": None,
    }
    for name in SOURCE_NAMES
}


def _mark(
    name: str,
    *,
    ok: bool,
    blocked: bool = False,
    latency_ms: int | None = None,
    error: str | None = None,
) -> None:
    """Record the outcome of the last fetch attempt for one source."""
    health = _HEALTH.setdefault(
        name,
        {
            "reachable": True,
            "blocked": False,
            "last_checked": None,
            "latency_ms": None,
            "error": None,
        },
    )
    health["reachable"] = ok and not blocked
    health["blocked"] = bool(blocked)
    health["last_checked"] = datetime.now(UTC).isoformat() + "Z"
    if latency_ms is not None:
        health["latency_ms"] = int(latency_ms)
    if error is not None:
        health["error"] = str(error)


def source_status(name: str | None = None) -> dict[str, Any]:
    """Per-source registry entry merged with live availability.

    Args:
        name: One source name (e.g. ``"oddsportal"``) or ``None`` for all.

    Returns:
        A mapping of source name -> ``{name, kind, base_url, confidence,
        requires_key, markets, notes, availability: {reachable, blocked,
        last_checked, latency_ms, error}}``. Never raises for unknown names
        (returns an empty dict).
    """
    if name is not None:
        entry = SOURCES.get(name)
        if entry is None:
            return {}
        return {"name": name, **entry, "availability": dict(_HEALTH.get(name, {}))}
    return {
        n: {"name": n, **SOURCES[n], "availability": dict(_HEALTH.get(n, {}))} for n in SOURCE_NAMES
    }


def available_sources() -> dict[str, dict[str, Any]]:
    """Return only the sources whose last fetch was reachable."""
    return {n: s for n, s in source_status().items() if s["availability"].get("reachable", False)}


# ── Transport (httpx + stealth headers, retry, TTL cache) ──────────────
_TIMEOUT = httpx.Timeout(12.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=1,
    base_delay=0.1,
    max_delay=0.4,
    retryable_exceptions=(httpx.HTTPError,),
)

_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
]

# 10s in-memory TTL cache on raw upstream responses (pollers run often).
_HTTP_CACHE_TTL = 10.0
_http_cache: dict[tuple[str, ...], tuple[float, str]] = {}


def _monotonic() -> float:
    """Injectable clock for cache expiry (tests control time)."""
    return time.monotonic()


def _cache_enabled() -> bool:
    """Return False while an HTTP mock (respx) is active.

    Same contract as :mod:`sports_data.odds`: when tests install respx
    routes they expect every request to be observed, so the cache is
    bypassed — otherwise a cached body would leak across tests that mock
    the same URL differently.
    """
    respx_mod = sys.modules.get("respx")
    if respx_mod is None:
        return True
    return not bool(getattr(respx_mod, "routes", []))


def _clear_cache() -> None:
    """Drop all cached upstream responses (exposed for tests/tuning)."""
    _http_cache.clear()


def _stealth_headers(url: str) -> dict[str, str]:
    """Browser-like request headers (rotate UA, sec-fetch, referer)."""
    parsed = urlparse(url)
    return {
        "User-Agent": _RNG.choice(_UA_POOL),
        "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"),
        "Accept-Language": _RNG.choice(
            ["en-US,en;q=0.9", "en-GB,en;q=0.8", "en-US,en;q=0.7,fr;q=0.3"]
        ),
        "Referer": f"https://{parsed.netloc}/",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "Connection": "keep-alive",
        "Cache-Control": "max-age=0",
    }


async def _fetch_text(url: str) -> str | None:
    """GET ``url`` (cached for :data:`_HTTP_CACHE_TTL` seconds) and return the body.

    Returns ``None`` on any failure (network, block, malformed payload).
    """
    key = (url,)
    if _cache_enabled():
        entry = _http_cache.get(key)
        if entry is not None:
            cached_at, cached_payload = entry
            if _monotonic() - cached_at < _HTTP_CACHE_TTL:
                return cached_payload
            _http_cache.pop(key, None)
    payload = await _fetch_uncached(url)
    if payload is not None and _cache_enabled():
        _http_cache[key] = (_monotonic(), payload)
    return payload


async def _fetch_uncached(url: str) -> str | None:
    """Perform the actual HTTP GET with retry/backoff (no caching)."""

    async def _one() -> str:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_stealth_headers(url), follow_redirects=True
        ) as client:
            response = await client.get(url)
            if response.status_code >= 500:
                response.raise_for_status()
            text = response.text
        if not text:
            raise ValueError("empty upstream response")
        return text

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


async def _fetch_json(url: str) -> Any | None:
    """GET ``url`` and parse JSON; ``None`` on any failure (never raises)."""
    text = await _fetch_text(url)
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None
