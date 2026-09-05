"""US geo-fenced sportsbook odds fetchers — hidden JSON endpoints.

Adds eleven US sportsbooks (DraftKings, FanDuel, BetMGM, Caesars, PointsBet,
BetRivers, Barstool, WynnBET, Betway US, Hard Rock, ESPN BET) to the Pry
sports engine. These books do **not** publish supported public odds APIs;
their consumer frontends call private JSON endpoints that are geo-fenced to
US IPs and (for most of them) protected by Incapsula / Akamai / session
cookies. This module reverse-engineers those endpoints and normalizes them
to the canonical odds schema from :mod:`sports_data.odds`.

Transport
---------
* Every fetch is routed through the **Webshare US residential proxy pool**
  first (:func:`webshare_proxy.next_webshare_proxy`) so the geo-fence sees a
  US IP. Webshare residential exits are US and are the only tier that can
  satisfy the geo check for these books.
* If the Webshare pool is empty it falls back to the local **Tor SOCKS5**
  tier (:func:`tor_fallback.fetch_via_tor`). Tor exit nodes are rarely US,
  so this tier usually cannot satisfy US geo-fences — it is a last resort,
  and failures there degrade to ``[]`` exactly like a geo-block.
* No tier raises. Any failure (empty proxy pool, proxy error, non-200,
  anti-bot interstitial, malformed JSON) returns ``[]`` for that book.

Contract
--------
* Every ``fetch_*`` is async and never raises — it returns ``[]`` on any
  failure (network, block, malformed payload, unsupported sport). One book
  being down never affects the others.
* Every record follows the canonical odds schema from :mod:`sports_data.odds`
  (``sport, event, event_id, market, book, bookmaker, home, away,
  home_odds, away_odds, draw_odds, spread, total, last_update, source``);
  ``source`` is ``"us_<book_id>"`` (e.g. ``"us_draftkings"``).
* :data:`US_BOOKS` is the static registry (id, name, category, odds url
  template, method, geo_required, confidence, notes);
  :func:`book_status` adds the live per-book availability seen by the last
  fetch.

Honesty notes
-------------
Confidence (0..1) reflects how reliably the book yields clean odds **through
a Webshare US residential proxy** today. DraftKings / PointsBet / BetRivers
are the most likely to work from a plain proxy; FanDuel sits behind Akamai
and usually needs warm session cookies; BetMGM's CDS API requires a
client-generated ``x-bwin-accessid`` token; Barstool, WynnBET, Betway US,
Hard Rock and ESPN BET are undocumented and/or defunct platforms that
typically need the browser tier (Camoufox) or a real US residential IP.

Module layout (split for size): pure normalization helpers live in
:mod:`datasets.sports_data.us_books_normalize`, per-book payload parsers in
:mod:`datasets.sports_data.us_books_parsers`, and the public ``fetch_*``
wrappers + :func:`fetch_us_odds` orchestrator in
:mod:`datasets.sports_data.us_books_api` (all re-exported here).

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio  # noqa: F401 - re-exported via us_books_api
import json
import logging
import random
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# ── Data-driven registry loader ─────────────────────────────────────────
# Static book metadata + sport→upstream-id maps live as plain JSON (data,
# not code) under ``data/us_books.json``; this module loads them at import.
_DATA_DIR = Path(__file__).resolve().parent / "data"


def _load_json(name: str) -> Any:
    with (_DATA_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


# SystemRandom: crypto-grade entropy so stealth jitter is not predictable.
_RNG = random.SystemRandom()

# Guarded imports — sports_data.odds is extended by a parallel agent and the
# Webshare/Tor helpers are optional runtime deps; degrade gracefully if any
# sibling is momentarily unavailable (parallel build safety).
try:
    from datasets.sports_data.odds import _SPORTS, _resolve_sports
except ImportError:  # pragma: no cover - parallel build guard
    _SPORTS = {}  # type: ignore[assignment]
    _resolve_sports = None  # type: ignore[assignment]

try:
    from pry.engine.tor_fallback import fetch_via_tor
except ImportError:  # pragma: no cover - optional dependency
    fetch_via_tor = None  # type: ignore[assignment]

try:
    from pry.engine.webshare_proxy import next_webshare_proxy
except ImportError:  # pragma: no cover - optional dependency
    next_webshare_proxy = None  # type: ignore[assignment]

# ── Book registry ──────────────────────────────────────────────────────
# Static per-book metadata. Confidence is a 0..1 estimate of how reliably
# the book yields clean odds through a Webshare US residential proxy today
# (not a hard promise) — see module docstring for the honesty notes.
# The registry itself is data-driven (JSON).
_US_BOOK_DATA: dict[str, Any] = _load_json("us_books.json")
US_BOOKS: dict[str, dict[str, Any]] = _US_BOOK_DATA["US_BOOKS"]

# Registry order also defines fetch_us_odds precedence when limit truncates.
_US_BOOK_IDS: tuple[str, ...] = tuple(US_BOOKS.keys())

# ── Per-book sport → upstream id maps (community-reverse-engineered) ───
# These drift seasonally / by state; an unmapped sport simply yields no URL
# and the fetcher returns [] (honest degrade, never a crash). Data-driven.
_DK_CATEGORY_IDS: dict[str, int] = _US_BOOK_DATA["_DK_CATEGORY_IDS"]
_FD_EVENT_GROUP_IDS: dict[str, int] = _US_BOOK_DATA["_FD_EVENT_GROUP_IDS"]
_PB_COMPETITION_IDS: dict[str, int] = _US_BOOK_DATA["_PB_COMPETITION_IDS"]
_BR_GROUP_IDS: dict[str, int] = _US_BOOK_DATA["_BR_GROUP_IDS"]

_PB_DETAIL_TEMPLATE = "https://api.pointsbet.com/api/v2/events/{event_key}"

# ── Live availability tracking ──────────────────────────────────────────
_HEALTH: dict[str, dict[str, Any]] = {
    book_id: {
        "reachable": True,
        "blocked": False,
        "last_checked": None,
        "latency_ms": None,
        "error": None,
    }
    for book_id in _US_BOOK_IDS
}


def _mark(
    book_id: str,
    *,
    ok: bool,
    blocked: bool = False,
    latency_ms: int | None = None,
    error: str | None = None,
) -> None:
    """Record the outcome of the last fetch attempt for one book."""
    health = _HEALTH.setdefault(
        book_id,
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
    health["last_checked"] = datetime.now(UTC).isoformat()
    if latency_ms is not None:
        health["latency_ms"] = int(latency_ms)
    if error is not None:
        health["error"] = str(error)


def book_status() -> dict[str, Any]:
    """Per-book registry entry merged with live availability.

    Returns a mapping of book id -> ``{id, name, category, odds_url_template,
    method, geo_required, confidence, notes, availability: {reachable,
    blocked, last_checked, latency_ms, error}}``. Never raises.
    """
    return {
        book_id: {"name": entry["name"], **entry, "availability": dict(_HEALTH[book_id])}
        for book_id, entry in US_BOOKS.items()
    }


# ── Transport (aiohttp + Webshare US proxy, Tor fallback, TTL cache) ───
_PROXY_TIMEOUT = 20.0
_TOR_TIMEOUT = 30.0
_HTTP_CACHE_TTL = 10.0
_http_cache: dict[str, tuple[float, Any]] = {}

_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

# Anti-bot interstitial markers (Incapsula / Akamai / Cloudflare).
_BLOCK_MARKERS = (
    "incapsula",
    "_incapsula",
    "akamai",
    "access denied",
    "forbidden",
    "challenge",
    "just a moment",
    "checking your browser",
    "captcha",
    "too many requests",
    "you have been blocked",
)


def _monotonic() -> float:
    """Injectable clock for cache expiry (tests control time)."""
    return time.monotonic()


def _cache_enabled() -> bool:
    """Return False while an HTTP mock is active.

    Mirrors the repo convention (sports_data.odds/sources): when tests
    install mocks they expect every request to be observed, so the in-memory
    TTL cache is bypassed to avoid cross-test leakage.
    """
    respx_mod = sys.modules.get("respx")
    if respx_mod is None:
        return True
    return not bool(getattr(respx_mod, "routes", []))


def _clear_cache() -> None:
    """Drop all cached upstream responses (exposed for tests/tuning)."""
    _http_cache.clear()


def _stealth_headers(referer: str) -> dict[str, str]:
    """Browser-like request headers for the book JSON endpoints."""
    parsed = urlparse(referer)
    return {
        "User-Agent": _RNG.choice(_UA_POOL),
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": referer,
        "Origin": f"https://{parsed.netloc}",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }


def _looks_blocked(text: str | None) -> bool:
    """True when the body smells like an anti-bot interstitial."""
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _BLOCK_MARKERS)


async def _fetch_json_via_proxy(url: str, referer: str) -> Any | None:
    """GET ``url`` (JSON) through Webshare US proxies, Tor fallback.

    Returns the parsed JSON object/array, or ``None`` on any failure —
    never raises. A non-200 response, an anti-bot interstitial, an empty
    body and a malformed JSON body all yield ``None`` (geo-block degrades
    to ``None`` exactly like a network failure).
    """
    key = url
    if _cache_enabled():
        entry = _http_cache.get(key)
        if entry is not None:
            cached_at, payload = entry
            if _monotonic() - cached_at < _HTTP_CACHE_TTL:
                return payload
            _http_cache.pop(key, None)
    payload = await _fetch_uncached_via_proxy(url, referer)
    if payload is not None and _cache_enabled():
        _http_cache[key] = (_monotonic(), payload)
    return payload


async def _fetch_uncached_via_proxy(url: str, referer: str) -> Any | None:
    """Perform the actual proxied HTTP GET (no caching); never raises."""
    import aiohttp

    headers = _stealth_headers(referer)
    proxy = next_webshare_proxy() if next_webshare_proxy is not None else None
    text: str | None = None
    try:
        if proxy:
            timeout = aiohttp.ClientTimeout(total=_PROXY_TIMEOUT)
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.get(url, headers=headers, proxy=proxy) as resp,
            ):
                if resp.status != 200:
                    return None
                text = await resp.text()
        elif fetch_via_tor is not None:
            # Tor tier: rarely a US exit, so this usually cannot satisfy US
            # geo-fences — included as the honest last resort.
            text = await fetch_via_tor(url, timeout=_TOR_TIMEOUT)
        else:
            return None
    except (aiohttp.ClientError, OSError, ValueError, TimeoutError):
        return None
    except Exception:  # noqa: BLE001 - contract: transport never raises
        logger.debug("us_books_proxy_fetch_error", extra={"url": url[:120]})
        return None
    if _looks_blocked(text):
        return None
    if not text or not text.strip():
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


# ── URL builders / per-book fetch core ──────────────────────────────────
def _build_url(book_id: str, canonical_sport: str) -> str | None:
    """Build the odds URL for one book + canonical sport, or None.

    Returns ``None`` when the book needs an id/token we do not have (e.g.
    BetMGM's ``x-bwin-accessid``) — the fetcher then honestly degrades to
    ``[]`` instead of firing a malformed request.
    """
    template = US_BOOKS[book_id]["odds_url_template"]
    if book_id == "draftkings":
        category_id = _DK_CATEGORY_IDS.get(canonical_sport)
        return template.format(category_id=category_id) if category_id is not None else None
    if book_id == "fanduel":
        group_id = _FD_EVENT_GROUP_IDS.get(canonical_sport)
        return template.format(event_group_id=group_id) if group_id is not None else None
    if book_id == "pointsbet":
        competition_id = _PB_COMPETITION_IDS.get(canonical_sport)
        return (
            template.format(competition_id=competition_id) if competition_id is not None else None
        )
    if book_id == "betrivers":
        group_id = _BR_GROUP_IDS.get(canonical_sport)
        return template.format(group_id=group_id) if group_id is not None else None
    url = template.replace("{sport}", canonical_sport)
    if "{" in url:
        # Unfilled placeholder (e.g. {access_id}) — cannot build a valid URL.
        return None
    return url


def _referer(book_id: str) -> str:
    """Book homepage used as the Referer header for its JSON calls."""
    netloc = urlparse(US_BOOKS[book_id]["odds_url_template"]).netloc
    return f"https://{netloc}/"


def _canonical_sport(slug: str) -> str:
    """Map a raw alias to the canonical odds key (e.g. ``nba`` -> ``basketball_nba``)."""
    if slug in _SPORTS:
        return _SPORTS[slug][0]
    return slug


def _clamp_limit(limit: int, maximum: int = 200) -> int:
    """Clamp a limit to a sane range."""
    try:
        return max(1, min(int(limit), maximum))
    except (TypeError, ValueError):
        return 50


async def _fetch_book(book_id: str, sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch + normalize one book's odds for a canonical sport key.

    Never raises: unsupported sport, unbuildable URL, geo-block, transport
    failure and malformed payloads all return ``[]``.
    """
    entry = US_BOOKS[book_id]
    start = _monotonic()
    url = _build_url(book_id, sport)
    if url is None:
        _mark(book_id, ok=False, error="no url for sport")
        return []
    payload = await _fetch_json_via_proxy(url, referer=_referer(book_id))
    if payload is None:
        _mark(book_id, ok=False, blocked=True, error="geo-block or transport failure")
        return []
    parser = _PARSERS[book_id]
    try:
        records = parser(payload, sport, book_id, entry["name"])
    except Exception:  # noqa: BLE001 - contract: per-book fetch never raises
        logger.debug("us_books_parse_error", extra={"book": book_id, "sport": sport})
        records = []
    _mark(
        book_id,
        ok=True,
        latency_ms=int((_monotonic() - start) * 1000),
        error=None if records else "no odds parsed",
    )
    return records[: _clamp_limit(limit)]


# ── Re-exports (parsers, helpers) ───────────────────────────────────────
# Kept importable from this module for backwards compatibility and because
# tests patch/access them here (e.g. ``us._parse_dk_eventgroup``).
from datasets.sports_data.us_books_parsers import (  # noqa: E402
    _parse_dk_eventgroup,
    _parse_fanduel_eventgroup,
    _parse_generic_events,
    _parse_pointsbet_events,
)

_PARSERS: dict[str, Callable[[Any, str, str, str], list[dict[str, Any]]]] = {
    "draftkings": _parse_dk_eventgroup,
    "fanduel": _parse_fanduel_eventgroup,
    "pointsbet": _parse_pointsbet_events,
    "betrivers": _parse_generic_events,
    "betmgm": _parse_generic_events,
    "caesars": _parse_generic_events,
    "barstool": _parse_generic_events,
    "wynnbet": _parse_generic_events,
    "betway_us": _parse_generic_events,
    "hardrock": _parse_generic_events,
    "espnbet": _parse_generic_events,
}


# ── Re-exports (public API) ─────────────────────────────────────────────
from datasets.sports_data.us_books_api import (  # noqa: E402,F401 - re-export
    _dispatch_book,
    _fetch_book_for,
    fetch_barstool,
    fetch_betmgm,
    fetch_betrivers,
    fetch_betway_us,
    fetch_caesars,
    fetch_draftkings,
    fetch_espnbet,
    fetch_fanduel,
    fetch_hardrock,
    fetch_pointsbet,
    fetch_us_odds,
    fetch_wynnbet,
)
