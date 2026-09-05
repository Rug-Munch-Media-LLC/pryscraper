"""Marathonbet, 1xBet and Betfair fetchers for Pry.

Extracted from :mod:`datasets.sports_data.european`:

* **Marathonbet** — server-rendered coupon pages (decimal odds rows).
* **1xBet** — internal ``LineFeed`` JSON endpoint (gzip/base64 payload).
* **Betfair** — public read-only Exchange endpoint
  (``/www/sports/exchange/readonly/v1/bymarket``) plus market-ID discovery
  from the exchange pages. No login required.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import base64
import gzip
import json
import logging
import re
import zlib
from typing import Any
from urllib.parse import urlencode

import httpx

import datasets.sports_data.offshore as offshore
import datasets.sports_data.sources as sources
from datasets.sports_data.european_common import (
    _1XBET_LEAGUE_KEYWORDS,
    _1XBET_SPORTS,
    _BETFAIR_SPORTS,
    _MARATHON_SPORTS,
    EUROPEAN_BOOKS,
    _canonical_sport,
    _mark_book,
)
from datasets.sports_data.offshore import (
    _fetch_json_geo,
    _fetch_text_geo,
    _looks_blocked,
    _parse_decimal_rows,
)
from datasets.sports_data.sources import _as_text, _to_float

logger = logging.getLogger(__name__)

# Guarded import: sports_data.odds helpers are optional (parallel build).
try:
    from datasets.sports_data.odds import _event_label
except ImportError:  # pragma: no cover - parallel build guard
    _event_label = None  # type: ignore[assignment]


# ── Marathonbet (server-rendered coupon) ────────────────────────────────
async def fetch_marathonbet(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch Marathonbet odds for one sport from the coupon pages.

    Marathonbet serves decimal-odds HTML rows (``coupon-row``) with the
    three-way (soccer) or two-way (NBA) layout; parsed by the generic
    decimal-rows parser shared with the offshore module.
    """
    name = "marathonbet"
    start = offshore._monotonic()
    try:
        canonical = _canonical_sport(sport)
        if canonical is None:
            return []
        path = _MARATHON_SPORTS.get(canonical)
        if path is None:
            _mark_book(
                name,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="unsupported sport",
            )
            return []
        url = f"{EUROPEAN_BOOKS[name]['base_url']}/{path}/"
        html = await _fetch_text_geo(url)
        if html is None:
            _mark_book(
                name,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="fetch failed",
            )
            return []
        if _looks_blocked(html):
            _mark_book(
                name,
                ok=False,
                blocked=True,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="anti-bot/geo block",
            )
            return []
        records = _parse_decimal_rows(html, canonical, name, "Marathonbet")
        for record in records:
            record["source"] = "european"
        records = records[: max(1, int(limit or 50))]
        if not records:
            _mark_book(
                name,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="no odds parsed",
            )
        else:
            _mark_book(name, ok=True, latency_ms=int((offshore._monotonic() - start) * 1000))
        return records
    except (httpx.HTTPError, OSError, ValueError):
        logger.warning("sports_european_failed", extra={"book": name, "sport": sport})
        _mark_book(
            name,
            ok=False,
            latency_ms=int((offshore._monotonic() - start) * 1000),
            error="fetch failed",
        )
        return []


# ── 1xBet (internal LineFeed JSON) ──────────────────────────────────────
def _decode_1xbet_payload(payload: dict[str, Any]) -> Any | None:
    """Decode the 1xBet ``Value`` field (base64 -> gzip/zlib -> JSON)."""
    value = payload.get("Value")
    if not isinstance(value, str) or not value:
        return None
    try:
        raw = base64.b64decode(value)
    except (ValueError, TypeError):
        return None
    for decompressor in (gzip.decompress, zlib.decompress):
        try:
            return json.loads(decompressor(raw).decode("utf-8", "replace"))
        except (OSError, zlib.error, json.JSONDecodeError, UnicodeDecodeError):
            continue
    return None


def _parse_1xbet_payload(data: Any, canonical: str, keyword: str | None) -> list[dict[str, Any]]:
    """Map the decoded LineFeed JSON onto h2h records.

    Structure: ``L`` = leagues [{id, I: name}], ``E`` = events
    [{id, L: league id, S: start, T: [{N: team}...], G: [group]}] where the
    first group (``G == "1"``) holds the match-winner outcomes
    (``T`` in {1, X, 2}, ``P: {"1": decimal}``).
    """
    if not isinstance(data, dict):
        return []
    leagues: dict[Any, str] = {}
    for league in data.get("L") or []:
        if isinstance(league, dict) and isinstance(league.get("id"), int):
            leagues[league["id"]] = str(league.get("I") or "")
    records: list[dict[str, Any]] = []
    for event in data.get("E") or []:
        if not isinstance(event, dict):
            continue
        league_name = leagues.get(event.get("L"))
        if keyword and league_name and keyword not in league_name.lower():
            continue
        teams_raw = event.get("T") or []
        teams = [str(t.get("N") or "") for t in teams_raw if isinstance(t, dict) and t.get("N")]
        if len(teams) < 2:
            continue
        away, home = teams[0], teams[1]  # 1xBet lists participants away-first
        event_label = (
            f"{away} @ {home}"
            if _event_label is None
            else (_event_label(home, away) or f"{away} @ {home}")
        )
        outcomes: dict[str, float] = {}
        groups = event.get("G") or []
        for group in groups:
            if not isinstance(group, dict):
                continue
            if str(group.get("G") or "") != "1":
                continue
            for outcome in group.get("E") or []:
                if not isinstance(outcome, dict):
                    continue
                key = str(outcome.get("T") or "")
                price = outcome.get("P")
                if not isinstance(price, dict):
                    continue
                value = _to_float(price.get("1"))
                if value is not None and value > 1:
                    outcomes[key] = round(value, 2)
            break
        home_odds = outcomes.get("1")
        away_odds = outcomes.get("2")
        if home_odds is None or away_odds is None:
            continue
        records.append(
            sources._record(  # type: ignore[attr-defined]
                sport=canonical,
                event=event_label,
                event_id=str(event.get("id")),
                market="h2h",
                book="1xbet",
                bookmaker="1xBet",
                home=home,
                away=away,
                home_odds=home_odds,
                away_odds=away_odds,
                draw_odds=outcomes.get("X"),
                last_update=_as_text(event.get("S")),
                source="european",
            )
        )
    return records


async def fetch_1xbet(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch 1xBet odds for one sport via the internal LineFeed endpoint."""
    name = "1xbet"
    start = offshore._monotonic()
    try:
        canonical = _canonical_sport(sport)
        if canonical is None:
            return []
        sport_id = _1XBET_SPORTS.get(canonical)
        if sport_id is None:
            _mark_book(
                name,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="unsupported sport",
            )
            return []
        query = urlencode(
            {
                "sport": sport_id,
                "lng": "en",
                "tf": "2200000",
                "tz": "3",
                "mode": "4",
                "country": "1",
            }
        )
        url = f"{EUROPEAN_BOOKS[name]['base_url']}/Get1x2_VZip?{query}"
        payload = await _fetch_json_geo(url)
        if not isinstance(payload, dict):
            _mark_book(
                name,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="fetch failed",
            )
            return []
        data = _decode_1xbet_payload(payload)
        records = _parse_1xbet_payload(data, canonical, _1XBET_LEAGUE_KEYWORDS.get(canonical))
        records = records[: max(1, int(limit or 50))]
        if not records:
            _mark_book(
                name,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="no odds parsed",
            )
        else:
            _mark_book(name, ok=True, latency_ms=int((offshore._monotonic() - start) * 1000))
        return records
    except (httpx.HTTPError, OSError, ValueError):
        logger.warning("sports_european_failed", extra={"book": name, "sport": sport})
        _mark_book(
            name,
            ok=False,
            latency_ms=int((offshore._monotonic() - start) * 1000),
            error="fetch failed",
        )
        return []


# ── Betfair (public read-only Exchange API) ─────────────────────────────
_BETFAIR_EXCHANGE = "https://www.betfair.com/exchange/plus"
_BETFAIR_READONLY = "https://www.betfair.com/www/sports/exchange/readonly/v1"
# Public access key embedded in Betfair's own frontend (documented by the
# community scrapers); refresh if Betfair rotates it — [REVIEW].
_BETFAIR_AK = "nzIFcwyWhrlwYMrh"
_BETFAIR_TYPES = (
    "MARKET_STATE,RUNNER_STATE,RUNNER_EXCHANGE_PRICES_BEST,"
    "RUNNER_DESCRIPTION,MARKET_RATES,MARKET_DESCRIPTION,EVENT,RUNNER_METADATA"
)
_MARKET_ID_RE = re.compile(r'"marketId"\s*:\s*"(\d+\.\d+)"')


def _discover_market_ids(html: str, limit: int) -> list[str]:
    """Unique market ids embedded in an exchange page (in page order)."""
    seen: list[str] = []
    for market_id in _MARKET_ID_RE.findall(html or ""):
        if market_id not in seen:
            seen.append(market_id)
    return seen[: max(1, int(limit or 50))]


def _parse_betfair_markets(payload: Any, canonical: str) -> list[dict[str, Any]]:
    """Map the bymarket response (eventTypes/eventNodes/marketNodes) to h2h records.

    Runner order is used as the home/away/draw convention — Betfair lists
    runners in selection order, so this is best-effort: [REVIEW] a name
    match against a fixture list for reliable home/away attribution.
    """
    if not isinstance(payload, dict):
        return []
    records: list[dict[str, Any]] = []
    for event_type in payload.get("eventTypes") or []:
        if not isinstance(event_type, dict):
            continue
        for event_node in event_type.get("eventNodes") or []:
            if not isinstance(event_node, dict):
                continue
            event_name = _as_text((event_node.get("event") or {}).get("name"))
            for market_node in event_node.get("marketNodes") or []:
                if not isinstance(market_node, dict):
                    continue
                market_name = str(market_node.get("marketName") or "")
                if not re.search(r"match odds|match winner|1x2|2-way", market_name, re.I):
                    continue
                runners = market_node.get("runners") or []
                if not isinstance(runners, list) or len(runners) < 2:
                    continue
                back_prices: list[float] = []
                runner_names: list[str] = []
                for runner in runners:
                    if not isinstance(runner, dict):
                        continue
                    runner_names.append(str(runner.get("runnerName") or ""))
                    exchange = runner.get("exchange")
                    price = None
                    if isinstance(exchange, dict):
                        best = exchange.get("availableToBack") or []
                        if isinstance(best, list) and best and isinstance(best[0], dict):
                            price = _to_float(best[0].get("price"))
                    back_prices.append(price if price is not None else 0.0)
                prices = [p for p in back_prices if p > 0]
                if len(prices) < 2:
                    continue
                home = runner_names[0] or (event_name or "")
                away = runner_names[1] or ""
                draw_odds = back_prices[2] if len(back_prices) >= 3 and back_prices[2] > 0 else None
                if not home or not away:
                    continue
                event_label = (
                    f"{away} @ {home}"
                    if _event_label is None
                    else (_event_label(home, away) or f"{away} @ {home}")
                )
                records.append(
                    sources._record(  # type: ignore[attr-defined]
                        sport=canonical,
                        event=event_label,
                        event_id=str(market_node.get("marketId") or ""),
                        market="h2h",
                        book="betfair",
                        bookmaker="Betfair",
                        home=home,
                        away=away,
                        home_odds=back_prices[0] or None,
                        away_odds=back_prices[1] or None,
                        draw_odds=draw_odds,
                        last_update=None,
                        source="european",
                    )
                )
    return records


async def fetch_betfair(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch Betfair Exchange back odds for one sport via the read-only API.

    Discovers market ids from the exchange page, then pulls prices from the
    public ``bymarket`` endpoint (no login). Cloudflare-protected — a
    Webshare proxy retry is attempted when the direct request is blocked.
    """
    name = "betfair"
    start = offshore._monotonic()
    try:
        canonical = _canonical_sport(sport)
        if canonical is None:
            return []
        path = _BETFAIR_SPORTS.get(canonical)
        if path is None:
            _mark_book(
                name,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="unsupported sport",
            )
            return []
        page = await _fetch_text_geo(f"{_BETFAIR_EXCHANGE}/{path}")
        if page is None or _looks_blocked(page):
            _mark_book(
                name,
                ok=False,
                blocked=True,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="anti-bot/geo block",
            )
            return []
        market_ids = _discover_market_ids(page, limit)
        if not market_ids:
            _mark_book(
                name,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="no markets discovered",
            )
            return []
        query = urlencode(
            {
                "_ak": _BETFAIR_AK,
                "marketIds": ",".join(market_ids),
                "currencyCode": "USD",
                "locale": "en_GB",
                "rollupLimit": "2",
                "rollupModel": "STAKE",
                "types": _BETFAIR_TYPES,
                "alt": "json",
            }
        )
        payload = await _fetch_json_geo(f"{_BETFAIR_READONLY}/bymarket?{query}")
        records = _parse_betfair_markets(payload, canonical)
        records = records[: max(1, int(limit or 50))]
        if not records:
            _mark_book(
                name,
                ok=False,
                latency_ms=int((offshore._monotonic() - start) * 1000),
                error="no odds parsed",
            )
        else:
            _mark_book(name, ok=True, latency_ms=int((offshore._monotonic() - start) * 1000))
        return records
    except (httpx.HTTPError, OSError, ValueError):
        logger.warning("sports_european_failed", extra={"book": name, "sport": sport})
        _mark_book(
            name,
            ok=False,
            latency_ms=int((offshore._monotonic() - start) * 1000),
            error="fetch failed",
        )
        return []
