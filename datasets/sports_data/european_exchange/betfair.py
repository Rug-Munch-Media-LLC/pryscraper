"""Betfair public Exchange fetcher and market parser."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode

import httpx

import datasets.sports_data.offshore as offshore
import datasets.sports_data.sources as sources
from datasets.sports_data.european_common import (
    _BETFAIR_SPORTS,
    _canonical_sport,
    _mark_book,
)
from datasets.sports_data.european_exchange.common import _event_label, logger
from datasets.sports_data.offshore import _fetch_json_geo, _fetch_text_geo, _looks_blocked
from datasets.sports_data.sources import _as_text, _to_float

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
