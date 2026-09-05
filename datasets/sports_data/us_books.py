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
import json
import logging
import random
import re
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

# ── Canonical market keys (mirror sports_data.odds) ────────────────────
_MARKET_H2H = "h2h"
_MARKET_SPREADS = "spreads"
_MARKET_TOTALS = "totals"
_MARKETS = (_MARKET_H2H, _MARKET_SPREADS, _MARKET_TOTALS)

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


# ── Shared record / normalization helpers ───────────────────────────────
def _as_text(value: Any) -> str | None:
    """Coerce a JSON value to str/None ('' -> None)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_float(value: Any) -> float | None:
    """Coerce a JSON value to float/None ('' / garbage -> None)."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_team(name: Any) -> str:
    """Normalize a team name for fuzzy matching (lowercase alnum words)."""
    if name is None:
        return ""
    return " ".join(re.findall(r"[a-z0-9]+", str(name).lower()))


def _american_to_decimal(price: Any) -> float | None:
    """Convert American moneyline odds (e.g. -150, +125) to decimal odds."""
    value = _to_float(price)
    if value is None or value == 0:
        return None
    if value > 0:
        return round(1 + value / 100, 2)
    return round(1 + 100 / abs(value), 2)


def _event_label(home: str | None, away: str | None) -> str | None:
    """Compose the conventional 'Away @ Home' event label."""
    if not home or not away:
        return None
    return f"{away} @ {home}"


def _split_event_name(name: Any) -> tuple[str | None, str | None]:
    """Split an event name like 'Celtics @ Lakers' into (away, home).

    US books use the sportsbook convention 'Away @ Home'; 'vs'/'at'/' - '
    separators are accepted too. Returns ``(None, None)`` when unparseable.
    """
    if not name:
        return None, None
    # Separators must be surrounded by whitespace so "at" never matches
    # inside a team name like "Heats" (regex is case-insensitive).
    parts = re.split(
        r"\s+(?:@|vs\.?|at)\s+|\s+[-\u2013]\s+",
        str(name).strip(),
        maxsplit=1,
        flags=re.I,
    )
    if len(parts) < 2:
        return None, None
    away = _as_text(parts[0])
    home = _as_text(parts[1])
    if not away or not home:
        return None, None
    return away, home


def _record(
    *,
    sport: str,
    event: str,
    event_id: str | None,
    market: str,
    book: str,
    bookmaker: str,
    home: str | None,
    away: str | None,
    home_odds: float | None,
    away_odds: float | None,
    draw_odds: float | None = None,
    spread: float | None = None,
    total: float | None = None,
    last_update: str | None,
    source: str,
) -> dict[str, Any]:
    """Build one canonical odds record (same schema as sports_data.odds)."""
    return {
        "sport": sport,
        "event": event,
        "event_id": event_id,
        "market": market,
        "book": book,
        "bookmaker": bookmaker,
        "home": home,
        "away": away,
        "home_odds": home_odds,
        "away_odds": away_odds,
        "draw_odds": draw_odds,
        "spread": spread,
        "total": total,
        "last_update": last_update,
        "source": source,
    }


def _market_records(
    market: str,
    selections: list[dict[str, Any]],
    *,
    sport: str,
    event: str,
    event_id: str | None,
    book: str,
    bookmaker: str,
    home: str | None,
    away: str | None,
    last_update: str | None,
) -> list[dict[str, Any]]:
    """Map one normalized market block onto canonical odds records.

    ``selections`` is a list of ``{"name", "price" (decimal), "point"}``
    dicts (price/point may be None). Mirrors sports_data.odds._market_records
    so the output is byte-for-byte compatible with the shared schema.
    """
    if market == _MARKET_H2H:
        prices: dict[str, float] = {}
        for sel in selections:
            name = _as_text(sel.get("name"))
            price = _to_float(sel.get("price"))
            if name is not None and price is not None:
                prices.setdefault(name.lower(), price)
        home_price = prices.get(home.lower()) if home else None
        away_price = prices.get(away.lower()) if away else None
        draw_price = prices.get("draw") or prices.get("tie")
        if home_price is None and away_price is None:
            return []
        return [
            _record(
                sport=sport,
                event=event,
                event_id=event_id,
                market=_MARKET_H2H,
                book=book,
                bookmaker=bookmaker,
                home=home,
                away=away,
                home_odds=home_price,
                away_odds=away_price,
                draw_odds=draw_price,
                last_update=last_update,
                source=f"us_{book}",
            )
        ]

    if market == _MARKET_SPREADS:
        home_price = away_price = None
        home_point = away_point = None
        for sel in selections:
            name = _as_text(sel.get("name"))
            price = _to_float(sel.get("price"))
            point = _to_float(sel.get("point"))
            if name is None or price is None:
                continue
            if home and name.lower() == home.lower():
                home_price, home_point = price, point
            elif away and name.lower() == away.lower():
                away_price, away_point = price, point
        if home_price is None and away_price is None:
            return []
        spread = home_point
        if spread is None and away_point is not None:
            spread = -away_point
        return [
            _record(
                sport=sport,
                event=event,
                event_id=event_id,
                market=_MARKET_SPREADS,
                book=book,
                bookmaker=bookmaker,
                home=home,
                away=away,
                home_odds=home_price,
                away_odds=away_price,
                spread=spread,
                last_update=last_update,
                source=f"us_{book}",
            )
        ]

    if market == _MARKET_TOTALS:
        over_price = under_price = None
        total: float | None = None
        for sel in selections:
            name = _as_text(sel.get("name"))
            price = _to_float(sel.get("price"))
            point = _to_float(sel.get("point"))
            if name is None or price is None:
                continue
            if name.lower() in {"over", "o"}:
                over_price, total = price, point
            elif name.lower() in {"under", "u"}:
                under_price, total = price, point
        if over_price is None and under_price is None:
            return []
        return [
            _record(
                sport=sport,
                event=event,
                event_id=event_id,
                market=_MARKET_TOTALS,
                book=book,
                bookmaker=bookmaker,
                home=home,
                away=away,
                home_odds=over_price,
                away_odds=under_price,
                total=total,
                last_update=last_update,
                source=f"us_{book}",
            )
        ]

    return []


# ── Selection / market block normalization ──────────────────────────────
def _selection_price(sel: dict[str, Any]) -> float | None:
    """Decimal odds from any of the common selection price shapes."""
    odds = sel.get("odds")
    if isinstance(odds, dict):
        dec = _to_float(odds.get("decimal"))
        if dec is not None:
            return round(dec, 2)
        am = _to_float(odds.get("american"))
        if am is not None:
            return _american_to_decimal(am)
    dec = _to_float(sel.get("price"))
    if dec is not None:
        return round(dec, 2)
    am = _to_float(sel.get("oddsAmerican"))
    if am is not None:
        return _american_to_decimal(am)
    dec = _to_float(sel.get("decimalOdds"))
    if dec is not None:
        return round(dec, 2)
    # FanDuel cache shape: fractional numerator/denominator (price = 1 + up/down).
    up = _to_float(sel.get("currentpriceup"))
    down = _to_float(sel.get("currentpricedown"))
    if up is not None and down and down != 0:
        return round(1 + up / down, 2)
    return None


def _selection_point(sel: dict[str, Any]) -> float | None:
    """Handicap / total line from a selection, in several known shapes."""
    for key in ("handicap", "point", "line", "spread", "total"):
        value = _to_float(sel.get(key))
        if value is not None:
            return value
    return None


def _point_from_label(name: str) -> float | None:
    """Pull a trailing number from a label like 'Over 220.5' or 'Lakers -5.5'."""
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(name or ""))
    if match is None:
        return None
    return _to_float(match.group(0))


def _normalize_selection(sel: Any) -> dict[str, Any]:
    """Normalize one raw selection/outcome into ``{name, price, point}``."""
    if not isinstance(sel, dict):
        return {"name": None, "price": None, "point": None}
    name = _as_text(sel.get("label") or sel.get("name") or sel.get("participant"))
    point = _selection_point(sel)
    price = _selection_price(sel)
    if (
        point is None
        and name
        and (name.lower().startswith("over") or name.lower().startswith("under"))
    ):
        point = _point_from_label(name)
    return {"name": name, "price": price, "point": point}


def _selections_of(block: Any) -> list[dict[str, Any]]:
    """Collect selection dicts from a market block in several known shapes."""
    if not isinstance(block, dict):
        return []
    for key in ("selections", "outcomes", "betOfferRows"):
        values = block.get(key)
        if isinstance(values, list):
            return [_normalize_selection(v) for v in values if isinstance(v, dict)]
    # Flatten markets[0].outcomes (DraftKings nests outcomes under markets[]).
    markets = block.get("markets")
    if isinstance(markets, list) and markets:
        return _selections_of(markets[0] if isinstance(markets[0], dict) else {})
    outcomes = block.get("outcomes")
    if isinstance(outcomes, list):
        return [_normalize_selection(v) for v in outcomes if isinstance(v, dict)]
    return []


def _market_key(name: Any) -> str | None:
    """Map a raw market name to a canonical market key (h2h/spreads/totals)."""
    norm = _normalize_team(name)
    if not norm:
        return None
    if any(token in norm for token in ("moneyline", "h2h", "head head", "win")):
        return _MARKET_H2H
    if any(token in norm for token in ("spread", "handicap", "point spread")):
        return _MARKET_SPREADS
    if any(token in norm for token in ("total", "over under", "overunder")):
        return _MARKET_TOTALS
    return None


def _market_blocks(markets: Any) -> list[dict[str, Any]]:
    """Split a raw markets list into canonical blocks.

    Returns ``[{market, selections}]`` where ``selections`` are normalized
    ``{name, price, point}`` dicts. Blocks with no usable selections are
    dropped.
    """
    blocks: list[dict[str, Any]] = []
    if not isinstance(markets, list):
        return blocks
    for market in markets:
        if not isinstance(market, dict):
            continue
        key = _market_key(market.get("name") or market.get("marketType"))
        if key is None:
            continue
        selections = _selections_of(market)
        if not selections:
            continue
        blocks.append({"market": key, "selections": selections})
    return blocks


# ── Book-specific parsers ───────────────────────────────────────────────
def _event_identity(event: dict[str, Any], name: str | None) -> tuple[str | None, str | None]:
    """Derive (home, away) from explicit event fields or the event name."""
    home = _as_text(event.get("home")) or _as_text(event.get("homeTeam"))
    away = _as_text(event.get("away")) or _as_text(event.get("awayTeam"))
    if not home or not away:
        parsed_away, parsed_home = _split_event_name(name)
        home = home or parsed_home
        away = away or parsed_away
    return home, away


def _parse_dk_eventgroup(
    payload: Any,
    sport: str,
    book: str,
    bookmaker: str,
) -> list[dict[str, Any]]:
    """Parse a DraftKings eventgroups JSON payload into canonical records.

    Expected shape: ``{"groupedMarkets": [{"event": {...}, "moneyline":
    {...}, "spread": {...}, "total": {...}}, ...]}`` with an alternate
    ``main`` array of ``{"marketType": "MONEYLINE"|"SPREAD"|"TOTAL",
    "outcomes": [...]}`` blocks.
    """
    records: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return records
    grouped = payload.get("groupedMarkets")
    if not isinstance(grouped, list):
        return records
    last_update = _payload_timestamp(payload)
    for group in grouped:
        if not isinstance(group, dict):
            continue
        raw_event = group.get("event")
        event = raw_event if isinstance(raw_event, dict) else {}
        event_id = _as_text(event.get("id"))
        name = _as_text(event.get("name"))
        home, away = _event_identity(event, name)
        if not home or not away:
            continue
        event_label = _event_label(home, away) or name or ""
        blocks = _dk_blocks(group)
        for block in blocks:
            records.extend(
                _market_records(
                    block["market"],
                    block["selections"],
                    sport=sport,
                    event=event_label,
                    event_id=event_id,
                    book=book,
                    bookmaker=bookmaker,
                    home=home,
                    away=away,
                    last_update=last_update,
                )
            )
    return records


def _dk_blocks(group: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect canonical market blocks from one DraftKings group."""
    blocks: list[dict[str, Any]] = []
    for raw_key, market in (
        ("moneyline", _MARKET_H2H),
        ("spread", _MARKET_SPREADS),
        ("total", _MARKET_TOTALS),
    ):
        block = group.get(raw_key)
        selections = _selections_of(block)
        if selections:
            blocks.append({"market": market, "selections": selections})
    if blocks:
        return blocks
    main = group.get("main")
    if isinstance(main, list):
        for item in main:
            if not isinstance(item, dict):
                continue
            key = _market_key(item.get("marketType"))
            if key is None:
                continue
            selections = _selections_of(item)
            if selections:
                blocks.append({"market": key, "selections": selections})
    return blocks


def _parse_fanduel_eventgroup(
    payload: Any,
    sport: str,
    book: str,
    bookmaker: str,
) -> list[dict[str, Any]]:
    """Parse a FanDuel eventGroup JSON payload into canonical records.

    Expected shape: ``{"eventGroup": {...}, "events": [{"event": {...},
    "markets": [{"name": "Moneyline", "selections": [{"name": ..., "odds":
    {"american": ..., "decimal": ...}, "handicap": ...}]}]}]}``. Also handles
    the cache/psevent variant (``eventmarketgroups`` -> ``markets``).
    """
    records: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return records
    last_update = _payload_timestamp(payload)
    events = payload.get("events")
    if not isinstance(events, list):
        return _parse_fanduel_cache(payload, sport, book, bookmaker, last_update)
    for item in events:
        if not isinstance(item, dict):
            continue
        raw_event = item.get("event")
        event = raw_event if isinstance(raw_event, dict) else item
        event_id = _as_text(event.get("id"))
        name = _as_text(event.get("name"))
        home, away = _event_identity(event, name)
        if not home or not away:
            continue
        event_label = _event_label(home, away) or name or ""
        markets = item.get("markets")
        if markets is None:
            markets = event.get("markets")
        for block in _market_blocks(markets):
            records.extend(
                _market_records(
                    block["market"],
                    block["selections"],
                    sport=sport,
                    event=event_label,
                    event_id=event_id,
                    book=book,
                    bookmaker=bookmaker,
                    home=home,
                    away=away,
                    last_update=last_update,
                )
            )
    return records


def _parse_fanduel_cache(
    payload: dict[str, Any],
    sport: str,
    book: str,
    bookmaker: str,
    last_update: str | None,
) -> list[dict[str, Any]]:
    """Parse the FanDuel cache/psevent variant (eventmarketgroups)."""
    records: list[dict[str, Any]] = []
    groups = payload.get("eventmarketgroups")
    if not isinstance(groups, list):
        return records
    for group in groups:
        if not isinstance(group, dict):
            continue
        raw_event = group.get("event")
        event = raw_event if isinstance(raw_event, dict) else {}
        name = _as_text(event.get("name") or group.get("eventName"))
        home, away = _event_identity(event, name)
        if not home or not away:
            continue
        event_label = _event_label(home, away) or name or ""
        for block in _market_blocks(group.get("markets")):
            records.extend(
                _market_records(
                    block["market"],
                    block["selections"],
                    sport=sport,
                    event=event_label,
                    event_id=_as_text(event.get("id") or group.get("eventId")),
                    book=book,
                    bookmaker=bookmaker,
                    home=home,
                    away=away,
                    last_update=last_update,
                )
            )
    return records


def _parse_pointsbet_events(
    payload: Any,
    sport: str,
    book: str,
    bookmaker: str,
) -> list[dict[str, Any]]:
    """Parse a PointsBet featured-events JSON payload into canonical records.

    Expected shape: ``{"events": [{"id"/"key", "name", "markets": [{"name":
    "Moneyline"|"Point Spread"|"Total Points", "selections": [{"name",
    "price" (decimal), "point"}]}]}]}``.
    """
    records: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return records
    events = payload.get("events")
    if not isinstance(events, list):
        return records
    last_update = _payload_timestamp(payload)
    for item in events:
        if not isinstance(item, dict):
            continue
        event_id = _as_text(item.get("id") or item.get("key"))
        name = _as_text(item.get("name"))
        home, away = _event_identity(item, name)
        if not home or not away:
            continue
        event_label = _event_label(home, away) or name or ""
        markets = item.get("markets")
        if markets is None:
            markets = item.get("featuredMarkets")
        for block in _market_blocks(markets):
            records.extend(
                _market_records(
                    block["market"],
                    block["selections"],
                    sport=sport,
                    event=event_label,
                    event_id=event_id,
                    book=book,
                    bookmaker=bookmaker,
                    home=home,
                    away=away,
                    last_update=last_update,
                )
            )
    return records


def _parse_generic_events(
    payload: Any,
    sport: str,
    book: str,
    bookmaker: str,
) -> list[dict[str, Any]]:
    """Best-effort parser for books whose JSON shape is not well documented.

    Handles ``events`` / ``fixtures`` / ``eventGroups`` containers with
    either wrapped (``{"event": {...}}``) or flat event dicts carrying a
    ``markets`` array (FanDuel-like). Used by BetMGM, Caesars, Barstool,
    WynnBET, Betway US, Hard Rock and ESPN BET — those feeds are
    undocumented and session-bound, so this is honest best-effort: it only
    yields records when the payload happens to match a known shape.
    """
    records: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return records
    last_update = _payload_timestamp(payload)
    container: Any = None
    for key in ("events", "fixtures", "eventGroups", "offerGrouping"):
        candidate = payload.get(key)
        if isinstance(candidate, list):
            container = candidate
            break
    if container is None:
        return records
    for item in container:
        if not isinstance(item, dict):
            continue
        raw_event = item.get("event")
        event = raw_event if isinstance(raw_event, dict) else item
        event_id = _as_text(event.get("id") or event.get("eventId"))
        name = _as_text(event.get("name"))
        home, away = _event_identity(event, name)
        if not home or not away:
            continue
        event_label = _event_label(home, away) or name or ""
        markets = item.get("markets")
        if markets is None:
            markets = event.get("markets")
        for block in _market_blocks(markets):
            records.extend(
                _market_records(
                    block["market"],
                    block["selections"],
                    sport=sport,
                    event=event_label,
                    event_id=event_id,
                    book=book,
                    bookmaker=bookmaker,
                    home=home,
                    away=away,
                    last_update=last_update,
                )
            )
    return records


def _payload_timestamp(payload: Any) -> str:
    """Best-effort freshness timestamp from a payload, else now (UTC)."""
    if isinstance(payload, dict):
        for key in ("lastUpdate", "lastModified", "generatedAt", "timestamp"):
            value = _as_text(payload.get(key))
            if value:
                return value
    return datetime.now(UTC).isoformat()


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


# ── Public per-book fetchers (all async, never raise) ───────────────────
async def _fetch_book_for(book_id: str, sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Resolve a sport alias and delegate to the shared per-book core."""
    if _resolve_sports is None:
        return []
    slugs = _resolve_sports(sport)
    if not slugs:
        return []
    return await _fetch_book(book_id, _canonical_sport(slugs[0]), limit)


async def fetch_draftkings(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch DraftKings odds for one sport (US proxy required)."""
    return await _fetch_book_for("draftkings", sport, limit)


async def fetch_fanduel(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch FanDuel odds for one sport (US proxy + warm session often required)."""
    return await _fetch_book_for("fanduel", sport, limit)


async def fetch_betmgm(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch BetMGM odds for one sport (needs x-bwin-accessid; browser tier)."""
    return await _fetch_book_for("betmgm", sport, limit)


async def fetch_caesars(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch Caesars odds for one sport (browser tier usually required)."""
    return await _fetch_book_for("caesars", sport, limit)


async def fetch_pointsbet(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch PointsBet odds for one sport (public JSON feed)."""
    return await _fetch_book_for("pointsbet", sport, limit)


async def fetch_betrivers(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch BetRivers odds for one sport (US geo required)."""
    return await _fetch_book_for("betrivers", sport, limit)


async def fetch_barstool(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch Barstool odds for one sport (legacy; mostly folded into ESPN BET)."""
    return await _fetch_book_for("barstool", sport, limit)


async def fetch_wynnbet(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch WynnBET odds for one sport (platform shut down 2024)."""
    return await _fetch_book_for("wynnbet", sport, limit)


async def fetch_betway_us(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch Betway US odds for one sport (limited US footprint)."""
    return await _fetch_book_for("betway_us", sport, limit)


async def fetch_hardrock(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch Hard Rock odds for one sport (Kambi frontend, undocumented)."""
    return await _fetch_book_for("hardrock", sport, limit)


async def fetch_espnbet(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch ESPN BET odds for one sport (Penn internal API, browser tier)."""
    return await _fetch_book_for("espnbet", sport, limit)


# ── Orchestrator ────────────────────────────────────────────────────────
async def fetch_us_odds(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch US sportsbook odds across every book in :data:`US_BOOKS`.

    Args:
        sport: Canonical sport key or short alias (e.g. ``"basketball_nba"``
            or ``"nba"``); ``""`` / ``"all"`` resolves to the default sports
            (same as :func:`sports_data.odds.get_odds`).
        limit: Max records to return (default 50). Each book is fetched with
            this cap and the merged result is truncated to it.

    Returns:
        Canonical odds records from every book that responded, tagged
        ``source="us_<book_id>"``; ``[]`` when no book yielded odds (every
        book geo-blocked / failed) or the sport is unsupported. Never
        raises — each book is fetched independently via ``asyncio.gather``
        with ``return_exceptions=True`` so one failure never affects the
        others.
    """
    if _resolve_sports is None:
        return []
    slugs = _resolve_sports(sport)
    if not slugs:
        logger.warning("sports_us_books_unsupported_sport", extra={"sport": sport})
        return []
    clamped = _clamp_limit(limit)
    records: list[dict[str, Any]] = []
    for slug in slugs:
        jobs = [_dispatch_book(book_id, slug) for book_id in _US_BOOK_IDS]
        results = await asyncio.gather(*jobs, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                continue
            for record in result:
                if isinstance(record, dict):
                    records.append(record)
    records.sort(key=lambda record: str(record.get("last_update") or ""), reverse=True)
    return records[:clamped]


async def _dispatch_book(book_id: str, slug: str) -> list[dict[str, Any]]:
    """Fetch one book for one raw sport slug (gather-safe wrapper)."""
    try:
        return await _fetch_book(book_id, _canonical_sport(slug))
    except Exception:  # noqa: BLE001 - never-raise contract for the orchestrator
        return []
