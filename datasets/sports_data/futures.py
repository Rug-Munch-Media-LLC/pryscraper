"""Futures / championship odds — The Odds API outrights + ESPN fallback.

Futures are long-term markets ("Who will win the Super Bowl?", "NBA MVP",
"Next President") with many outcomes, priced by books under the Odds API
``outrights`` market (and dedicated ``*_championship`` sport keys).

Sources
-------
* **The Odds API** (``api.the-odds-api.com``) — ``markets=outrights`` per
  sport key, plus dedicated futures sport keys (e.g.
  ``basketball_nba_championship``) when a ``PRY_ODDS_API_KEY`` is
  configured (free tier: 500 requests/month).
* **ESPN public endpoints** (``site.api.espn.com``) — no key, no quota.
  Best-effort futures fetch from ESPN's league futures feed; degrades to
  ``[]`` when ESPN publishes none.

Contract
--------
* :func:`get_futures_odds` — async, never raises, returns a ``list``
  (``[]`` on failure). One record per futures market.
* :func:`get_futures_market` — async, never raises, returns a ``dict``
  (``{}`` on failure). Single market detail.

Record shape (``get_futures_odds``): ``{market_id, market_name, sport,
outcomes: [{name, price, implied_prob, book}], best_odds, best_book,
total_implied_prob, last_update, source}``. ``price`` is decimal odds;
``implied_prob`` is ``1 / decimal_odds``; ``total_implied_prob`` is the
sum across outcomes (the vig indicator — >1.0 means the book holds an
edge). ``best_odds``/``best_book`` aggregate the best price per outcome
across all books.

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
from typing import Any
from urllib.parse import quote

import httpx

from datasets.sports_data.odds import (
    _HEADERS,
    _TIMEOUT,
    _api_key,
    _as_text,
    _canonical_book,
    _fetch_json,
    _resolve_sports,
    _to_float,
)
from pry.engine.retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

# ── Transport (ESPN futures fetch — odds._fetch_json covers Odds API) ──
_RETRY_CONFIG = RetryConfig(
    max_retries=1,
    base_delay=0.1,
    max_delay=0.4,
    retryable_exceptions=(httpx.HTTPError,),
)

# Dedicated Odds API futures sport keys tried in addition to the base
# sport key (upstream publishes championships under suffixed keys).
_FUTURES_SUFFIXES = ("_championship", "_winner", "_mvp")

# ESPN futures endpoint candidates (best-effort; ESPN moves these around).
_ESPN_FUTURES_URLS = (
    "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/futures",
    "https://site.web.api.espn.com/apis/common/v3/sports/{sport}/{league}/futures",
)

# Default futures sports (mirrors the odds module's default slate).
_DEFAULT_FUTURES_SPORTS = ("basketball_nba", "americanfootball_nfl", "soccer_epl")


async def _espn_futures_for_league(
    espn: tuple[str, str] | None,
) -> list[dict[str, Any]]:
    """Best-effort ESPN futures fetch for one league (no key required)."""
    if espn is None:
        return []
    for url in _ESPN_FUTURES_URLS:
        formatted = url.format(sport=espn[0], league=espn[1])
        payload = await _fetch_json(formatted)
        if isinstance(payload, dict) and payload.get("futures"):
            return _map_espn_futures(payload, espn)
    return []


def _map_espn_futures(payload: dict[str, Any], espn: tuple[str, str]) -> list[dict[str, Any]]:
    """Flatten an ESPN futures payload into normalized market records."""
    slug = f"{espn[0]}_{espn[1]}"
    records: list[dict[str, Any]] = []
    for raw in payload.get("futures") or []:
        if not isinstance(raw, dict):
            continue
        category = _as_text(raw.get("category")) or "Futures"
        provider = raw.get("provider") or {}
        book = _canonical_book(_as_text(provider.get("name")))
        outcomes: list[dict[str, Any]] = []
        for entry in raw.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            name = _as_text((entry.get("athlete") or {}).get("displayName")) or _as_text(
                (entry.get("team") or {}).get("displayName")
            )
            price = _to_float((entry.get("odds") or {}).get("americanValue"))
            if not name or price is None:
                continue
            decimal = _american_to_decimal(price)
            if decimal is None:
                continue
            outcomes.append(
                {
                    "name": name,
                    "price": decimal,
                    "implied_prob": round(1 / decimal, 6),
                    "book": book,
                }
            )
        if not outcomes:
            continue
        records.append(
            _build_market_record(
                market_id=f"{slug}:{_as_text(raw.get('id')) or category}",
                market_name=_as_text(raw.get("name")) or category,
                sport=slug,
                outcomes=outcomes,
                source="espn",
            )
        )
    return records


def _american_to_decimal(price: float) -> float | None:
    """Convert American odds (e.g. -150, +125) to decimal odds."""
    if price == 0:
        return None
    if price > 0:
        return round(1 + price / 100, 2)
    return round(1 + 100 / abs(price), 2)


def _build_market_record(
    market_id: str,
    market_name: str,
    sport: str,
    outcomes: list[dict[str, Any]],
    source: str,
) -> dict[str, Any]:
    """Normalize one futures market: implied probs + best-odds aggregation."""
    # Best odds per outcome name across all books.
    best: dict[str, dict[str, Any]] = {}
    for outcome in outcomes:
        name = str(outcome.get("name") or "")
        current = best.get(name)
        if current is None or float(outcome.get("price") or 0) > float(current.get("price") or 0):
            best[name] = outcome
    best_outcomes = sorted(best.values(), key=lambda o: float(o.get("price") or 0))
    top = best_outcomes[0] if best_outcomes else None
    total_implied = round(sum(float(o.get("implied_prob") or 0) for o in best_outcomes), 6)
    return {
        "market_id": market_id,
        "market_name": market_name,
        "sport": sport,
        "outcomes": outcomes,
        "best_odds": float(top.get("price")) if top else None,
        "best_book": top.get("book") if top else None,
        "total_implied_prob": total_implied,
        "source": source,
    }


def _map_odds_api_futures(
    raw: dict[str, Any], slug: str, source: str = "the_odds_api"
) -> dict[str, Any] | None:
    """Map one Odds API outrights event (a futures market) to a record."""
    event_id = _as_text(raw.get("id"))
    bookmakers = raw.get("bookmakers")
    if not event_id or not isinstance(bookmakers, list):
        return None
    outcomes: list[dict[str, Any]] = []
    for bookmaker in bookmakers:
        if not isinstance(bookmaker, dict):
            continue
        book = _canonical_book(_as_text(bookmaker.get("key")))
        for market in bookmaker.get("markets") or []:
            if not isinstance(market, dict):
                continue
            for outcome in market.get("outcomes") or []:
                if not isinstance(outcome, dict):
                    continue
                name = _as_text(outcome.get("name"))
                price = _to_float(outcome.get("price"))
                if not name or not price or price <= 1:
                    continue
                outcomes.append(
                    {
                        "name": name,
                        "price": price,
                        "implied_prob": round(1 / price, 6),
                        "book": book,
                    }
                )
    if not outcomes:
        return None
    return _build_market_record(
        market_id=f"{slug}:{event_id}",
        market_name=_as_text(raw.get("title")) or _as_text(raw.get("sport_key")) or slug,
        sport=slug,
        outcomes=outcomes,
        source=source,
    )


async def _odds_api_futures_for_sport(slug: str) -> list[dict[str, Any]]:
    """Fetch outrights (futures) for one sport from The Odds API."""
    key = _api_key()
    if not key:
        return []
    records: list[dict[str, Any]] = []
    # Base sport key with outrights market, then dedicated futures keys.
    candidates = [slug] + [f"{slug}{suffix}" for suffix in _FUTURES_SUFFIXES]
    for odds_key in candidates:
        params = {
            "apiKey": key,
            "regions": "us",
            "markets": "outrights",
            "oddsFormat": "decimal",
        }
        url = f"https://api.the-odds-api.com/v4/sports/{quote(odds_key)}/odds"
        payload = await _fetch_json(url, params)
        if not isinstance(payload, list):
            continue
        for raw in payload:
            if isinstance(raw, dict):
                record = _map_odds_api_futures(raw, slug)
                if record is not None:
                    records.append(record)
        if records:
            break  # base key already returned futures; skip suffixed keys
    return records


async def get_futures_odds(sport: str = "all", limit: int = 20) -> list[dict[str, Any]]:
    """Fetch futures/championship odds across books for one or more sports.

    Args:
        sport: Sport key or alias (e.g. ``"nba"``, ``"basketball_nba"``)
            or ``"all"`` (default: NBA + NFL + EPL).
        limit: Max market records to return (1-100).

    Returns:
        A list of normalized futures market dicts (see module docstring).
        ``[]`` on failure or invalid sport. Never raises.
    """
    try:
        return await _get_futures_odds(sport, limit)
    except Exception:
        logger.exception("sports_futures_crashed", extra={"sport": sport, "limit": limit})
        return []


async def _get_futures_odds(sport: str, limit: int) -> list[dict[str, Any]]:
    slugs = _resolve_sports(sport) or (
        list(_DEFAULT_FUTURES_SPORTS) if str(sport or "").strip().lower() in {"", "all"} else []
    )
    if not slugs:
        logger.warning("sports_futures_invalid_sport", extra={"sport": sport})
        return []
    clamped = max(1, min(int(limit), 100))
    records: list[dict[str, Any]] = []
    for slug in slugs:
        odds_key, espn = _SPORTS_TABLE.get(slug, (slug, None))
        records.extend(await _odds_api_futures_for_sport(odds_key))
        if not records or not _api_key():
            records.extend(await _espn_futures_for_league(espn))
    # Dedup by market_id (suffixed keys can overlap the base key).
    seen: set[str] = set()
    deduped = []
    for record in records:
        market_id = str(record.get("market_id") or "")
        if market_id in seen:
            continue
        seen.add(market_id)
        deduped.append(record)
    deduped.sort(key=lambda r: str(r.get("market_name") or ""))
    return deduped[:clamped]


async def get_futures_market(market_id: str) -> dict[str, Any]:
    """Fetch a single futures market by id.

    Args:
        market_id: The market id as returned by :func:`get_futures_odds`
            (``sport:event_id``), e.g. ``"basketball_nba:abc123"``.

    Returns:
        The normalized market dict, or ``{}`` on failure. Never raises.
    """
    try:
        return await _get_futures_market(market_id)
    except Exception:
        logger.exception("sports_futures_market_crashed", extra={"market_id": market_id})
        return {}


async def _get_futures_market(market_id: str) -> dict[str, Any]:
    raw_id = str(market_id or "").strip()
    if not raw_id:
        return {}
    prefix, _, rest = raw_id.partition(":")
    if not rest:
        # No sport prefix — scan the default futures sports.
        slugs = list(_DEFAULT_FUTURES_SPORTS)
        target_id = raw_id
    else:
        resolved = _resolve_sports(prefix)
        if not resolved:
            return {}
        slugs = resolved
        target_id = rest
    key = _api_key()
    for slug in slugs:
        odds_key, _espn = _SPORTS_TABLE.get(slug, (slug, None))
        if key:
            params = {
                "apiKey": key,
                "regions": "us",
                "markets": "outrights",
                "oddsFormat": "decimal",
            }
            url = f"https://api.the-odds-api.com/v4/sports/{quote(odds_key)}/odds"
            payload = await _fetch_json(url, params)
            if isinstance(payload, list):
                for raw in payload:
                    if isinstance(raw, dict) and _as_text(raw.get("id")) == target_id:
                        record = _map_odds_api_futures(raw, slug)
                        if record is not None:
                            return record
    return {}


# ── Sport table (lazy import to avoid odds.py import cycles) ──────────
def _sport_table() -> dict[str, tuple[str, tuple[str, str] | None]]:
    from datasets.sports_data.odds_common import _SPORTS

    return _SPORTS


_SPORTS_TABLE: dict[str, tuple[str, tuple[str, str] | None]] = _sport_table()

# Re-exported transport helpers kept importable for tests.
__all__ = [
    "_HEADERS",
    "_RETRY_CONFIG",
    "_TIMEOUT",
    "async_retry",
    "get_futures_market",
    "get_futures_odds",
]
