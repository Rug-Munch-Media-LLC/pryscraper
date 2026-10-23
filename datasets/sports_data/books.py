"""Sportsbook registry + generic odds scraper — "more sources than anyone, free".

This module is the public facade; the implementation lives in focused
siblings:

* :mod:`datasets.sports_data.books_registry` — :data:`BOOKS`, a registry of
  ~110 real sportsbooks (US, offshore, UK, EU, Asian) with per-book fetch
  metadata (``id``, ``name``, ``category``, ``region``, ``odds_url_template``,
  ``method``, ``confidence``, ``geo_required``, ``notes``), loaded from
  ``data/books.json``. No paid APIs, no API keys — every book is reached
  through Pry's own scraping stack.
* :mod:`datasets.sports_data.books_transport` — plain httpx + stealth
  headers + retry, escalation to :class:`ultimate_scraper.UltimateScraper`
  (httpx -> TLS impersonation -> cloudscraper -> FlareSolverr -> Camoufox ->
  Playwright -> Tor -> premium proxy -> archive) for browser-tier or
  geo-fenced books, and Webshare residential proxies for ``geo_required``
  books.
* :mod:`datasets.sports_data.books_extract` — payload → records: embedded
  states (``__NEXT_DATA__``, ``__NUXT__``, ``__INITIAL_STATE__``,
  ``_dida_config_``, JSON-LD), JSON-tree walking, HTML tables, dedupe.
* :mod:`datasets.sports_data.books_markets` — per-market record builders
  (h2h / spreads / totals) from JSON trees.
* :mod:`datasets.sports_data.books_normalize` — price normalization
  (American / fractional / decimal → decimal) and the canonical record.

Contract
--------
* :func:`scrape_book_odds` — async, never raises, returns ``list`` (``[]``
  on failure/unknown book). One record per (event, market).
* :func:`get_all_books_odds` — async, never raises; aggregates every
  reachable book concurrently (per-book degradation, capped concurrency).
  This is the "more sources than anyone" endpoint.
* :func:`books_coverage` — sync registry statistics.

Normalized record schema::

    {
        "sport": "nba",
        "event": "Lakers @ Celtics",
        "market": "h2h",
        "book": "DraftKings",          # display name
        "book_id": "draftkings",       # registry id
        "home": "Los Angeles Lakers",
        "away": "Boston Celtics",
        "home_odds": 1.91,             # decimal odds
        "away_odds": 2.10,
        "draw_odds": None,             # 3-way markets only
        "spread": None,                # spreads market only
        "total": None,                 # totals market only
        "last_update": "2026-08-16T12:00:00Z",
        "source": "books:draftkings",
    }

Odds are normalized to decimal; American (``-110``, ``+120``) and fractional
(``5/2``) prices are converted.

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
import logging
import sys
from typing import Any

from datasets.sports_data.books_extract import _records_from_payload
from datasets.sports_data.books_normalize import _decimal_odds  # noqa: F401 (tests)
from datasets.sports_data.books_registry import (  # noqa: F401 (re-exports)
    BOOKS,
    CATEGORIES,
    METHODS,
    books_coverage,
    validate_registry,
)
from datasets.sports_data.books_transport import (
    _plain_fetch,
    _render_url,
    _scrape_with_ultimate,
)
from datasets.sports_data.cache import TTLCache

logger = logging.getLogger(__name__)

# ── Concurrency / timeout knobs for the aggregate endpoint ───────────────
_MAX_CONCURRENT = 8  # books fetched in parallel (browser tiers are heavy)
_PER_BOOK_TIMEOUT = 45.0  # hard per-book ceiling so one slow book never stalls all


async def _fetch_payload(book: dict[str, Any], url: str) -> tuple[str | None, str]:
    """Fetch one book's page/feed: returns (payload, kind in {"json","html"}).

    For ``json`` books a JSON endpoint is fetched directly (Bovada-style
    public feeds). For everything else an HTML page is fetched; browser-tier
    and geo-fenced books escalate through UltimateScraper when the plain
    HTTP attempt is blocked or empty. Never raises.

    Kept in this module (not ``books_transport``) so tests can monkeypatch
    ``books._fetch_payload`` / ``books._plain_fetch`` /
    ``books._scrape_with_ultimate`` and have :func:`scrape_book_odds`
    observe the substitution.
    """
    from datasets.sports_data.books_transport import _geo_proxy, _looks_blocked

    method = str(book.get("method", "html"))
    geo = bool(book.get("geo_required"))
    proxy = _geo_proxy() if geo else None

    if method == "json":
        text = await _plain_fetch(url, proxy=proxy)
        if text:
            return text, "json"
        html = await _scrape_with_ultimate(url, browser=False, geo_required=geo)
        if html:
            return html, "json"
        return None, "json"

    text = await _plain_fetch(url, proxy=proxy)
    if text and not _looks_blocked(text):
        return text, "html"
    need_browser = method == "browser" or geo
    if need_browser or text is None or _looks_blocked(text):
        html = await _scrape_with_ultimate(url, browser=need_browser, geo_required=geo)
        if html:
            return html, "html"
    return text, "html"


# ── Public API ───────────────────────────────────────────────────────────
async def scrape_book_odds(
    book_id: str,
    sport: str,
    market: str = "h2h",
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Scrape one sportsbook's odds with Pry's intelligent fallback.

    Results are cached for :data:`_BOOKS_CACHE_TTL_SECONDS` seconds so a
    poller (or a 112-book :func:`get_all_books_odds` pass) never re-scrapes
    the same book within the window. The cache is bypassed while an HTTP
    mock (respx) is active so tests observe every request.

    Args:
        book_id: Registry id (e.g. ``"draftkings"``, ``"bovada"``).
        sport: Sport slug (e.g. ``"nba"``, ``"basketball_nba"``).
        market: ``"h2h"`` (default), ``"spreads"``, ``"totals"`` or ``"all"``.
        limit: Max records to return.

    Returns:
        A list of normalized odds records (see module docstring). ``[]`` on
        failure or unknown book. Never raises.
    """
    try:
        key = ("book", book_id, sport, market, int(limit))
        use_cache = _cache_enabled()
        if use_cache:
            cached = _books_cache.get(key)
            if cached is not None:
                return cached
        book = BOOKS.get(book_id)
        if book is None:
            return []
        url = _render_url(book["odds_url_template"], sport)
        payload, kind = await _fetch_payload(book, url)
        if not payload:
            return []
        records = _records_from_payload(book, payload, kind, sport, market, limit)
        if use_cache:
            _books_cache.set(key, records)
        return records
    except Exception:  # handler logs the exception, so BLE001 is satisfied
        logger.exception("books_scrape_crashed", extra={"book_id": book_id, "sport": sport})
        return []


async def get_all_books_odds(
    sport: str,
    market: str = "h2h",
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Aggregate odds across every reachable book — "more sources than anyone".

    Every book is fetched concurrently (capped at :data:`_MAX_CONCURRENT`)
    with per-book degradation: a dead/blocked book contributes nothing and
    never blanks the result. ``limit`` caps the total records returned.

    The aggregated result is cached for :data:`_BOOKS_CACHE_TTL_SECONDS`
    seconds (each book is also cached individually inside
    :func:`scrape_book_odds`), so back-to-back 112-book polls never
    re-scrape. The cache is bypassed while an HTTP mock (respx) is active
    or when :func:`scrape_book_odds` has been substituted, so tests and
    embedders injecting fakes always observe fresh behavior.

    Returns:
        A list of normalized odds records from every reachable book.
        ``[]`` on total failure. Never raises.
    """
    try:
        key = ("all_books", sport, market, int(limit))
        use_cache = _aggregate_cache_enabled()
        if use_cache:
            cached = _books_cache.get(key)
            if cached is not None:
                return cached
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT)

        async def _one(book_id: str) -> list[dict[str, Any]]:
            async with semaphore:
                try:
                    return await asyncio.wait_for(
                        scrape_book_odds(book_id, sport, market=market, limit=limit),
                        timeout=_PER_BOOK_TIMEOUT,
                    )
                except Exception as exc:  # noqa: BLE001 - per-book degradation
                    logger.warning(
                        "book_odds_unavailable",
                        extra={"book": book_id, "sport": sport, "error": str(exc)[:120]},
                    )
                    return []

        results = await asyncio.gather(
            *(_one(book_id) for book_id in BOOKS), return_exceptions=True
        )
        records: list[dict[str, Any]] = []
        for result in results:
            if isinstance(result, list):
                records.extend(result)
        records = records[:limit]
        if use_cache:
            _books_cache.set(key, records)
        return records
    except Exception:  # handler logs the exception, so BLE001 is satisfied
        logger.exception("books_get_all_crashed", extra={"sport": sport, "market": market})
        return []


# ── 30s TTL cache for book polls ─────────────────────────────────────────
# A second ``scrape_book_odds`` / ``get_all_books_odds`` call within the
# TTL window returns the cached records instead of re-scraping up to 112
# books. The cache is bypassed while an HTTP mock (respx) is active so
# tests observe every request; the aggregate cache is additionally disabled
# whenever the module's own ``scrape_book_odds`` has been substituted
# (monkeypatched fakes must always be observed fresh).
_BOOKS_CACHE_TTL_SECONDS = 30.0
_books_cache = TTLCache(capacity=768, default_ttl=_BOOKS_CACHE_TTL_SECONDS)
_original_scrape_book_odds = scrape_book_odds


def _cache_enabled() -> bool:
    """Return False while an HTTP mock (respx) is active.

    The cache exists to stop production pollers re-scraping 112 books.
    When tests install respx routes they expect every request to be
    observed, so the cache is bypassed — otherwise a cached result would
    leak across tests that mock the same URL differently.
    """
    respx_mod = sys.modules.get("respx")
    if respx_mod is None:
        return True
    return not bool(getattr(respx_mod, "routes", []))


def _aggregate_cache_enabled() -> bool:
    """Return False while HTTP mocks are active or ``scrape_book_odds`` is swapped.

    The aggregate cache in :func:`get_all_books_odds` stores whole-poll
    results; it must neither serve nor store results produced through a
    substituted scraper (monkeypatched tests, embedder fakes), because the
    caller expects every call to observe the fake.
    """
    if not _cache_enabled():
        return False
    return scrape_book_odds is _original_scrape_book_odds


def clear_books_cache() -> None:
    """Drop all cached book-scraper results (exposed for tests/tuning)."""
    _books_cache.clear()
