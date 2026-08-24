"""Multi-source sports odds fetchers + cross-source merge for Pry.

Extends the odds engine (:mod:`sports_data.odds`, The Odds API + ESPN) with
three additional free sources so a single dead/blocked/quota-bound source
never blanks the odds feed:

* **OddsPortal** (``www.oddsportal.com``) — consumer odds-comparison site
  with 80+ bookmakers across every sport. Match-listing pages are
  server-rendered HTML; the per-match bookmaker odds table is partly
  client-rendered and the site runs anti-bot protection, so plain HTTP only
  sees odds rows when the server includes them. Blocks are detected and
  flagged honestly (never silently treated as "no odds").
* **Bovada** (``www.bovada.lv``) — offshore book with a public JSON odds
  feed (``/services/sports/event/v2/events/A/description/{sport}[/{league}]``).
  Returns h2h, spreads and totals as decimal odds.
* **BetOnline** (``www.betonline.ag``) — offshore book; no public JSON API,
  so this fetcher parses the sportsbook listing pages (best-effort; the
  listing markup is server-rendered HTML with inline US-format odds).

Contract
--------
* Every ``fetch_*`` is async and never raises — it returns ``[]`` on any
  failure (network, block, malformed payload, unsupported sport). One source
  being down never affects the others.
* Every record follows the canonical odds schema from
  :mod:`sports_data.odds` (``sport, event, event_id, market, book, bookmaker,
  home, away, home_odds, away_odds, draw_odds, spread, total, last_update,
  source``) and is tagged with its origin ``source``.
* :data:`SOURCES` is the static registry (kind, base url, confidence,
  markets, notes); :func:`source_status` / :func:`available_sources` add the
  live per-source availability seen by the last fetch.
* :func:`merge_odds` dedupes records across sources by (event, market, book),
  prefers sharp books (Pinnacle) on conflict, and keeps the winning record's
  ``source`` tag.

Free-API terms: OddsPortal (consumer site, no API), Bovada / BetOnline
(unofficial public feeds — scrape politely, expect geo-blocks and layout
drift).

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
from typing import Any
from urllib.parse import urlparse

import httpx
from lxml import html as _lxml_html

from pry.engine.retry import RetryConfig, async_retry

# Guarded import: sports_data.odds is extended by a parallel agent; this
# module is imported by the package during init, so degrade gracefully if
# the sibling is momentarily unavailable (parallel build safety).
try:
    from sports_data.odds import (
        _SPORTS,
        _american_to_decimal,
        _canonical_book,
        _event_label,
        _resolve_sports,
    )
except ImportError:  # pragma: no cover - parallel build guard
    _SPORTS = {}  # type: ignore[assignment]
    _american_to_decimal = None  # type: ignore[assignment]
    _canonical_book = None  # type: ignore[assignment]
    _event_label = None  # type: ignore[assignment]
    _resolve_sports = None  # type: ignore[assignment]

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
# not a stable API contract.
SOURCES: dict[str, dict[str, Any]] = {
    "the_odds_api": {
        "kind": "api",
        "base_url": "https://api.the-odds-api.com/v4",
        "confidence": 0.95,
        "requires_key": True,
        "markets": ["h2h", "spreads", "totals", "outrights"],
        "notes": "Official market-standard odds API; quota-bound free tier (500 req/mo).",
    },
    "espn": {
        "kind": "api",
        "base_url": "https://site.api.espn.com/apis/site/v2",
        "confidence": 0.85,
        "requires_key": False,
        "markets": ["h2h", "spreads", "totals"],
        "notes": "Public scoreboards publish a moneyline/spread/total odds block; no key, coverage varies by league.",
    },
    "oddsportal": {
        "kind": "scrape",
        "base_url": "https://www.oddsportal.com",
        "confidence": 0.4,
        "requires_key": False,
        "markets": ["h2h"],
        "notes": "80+ books, all sports. Listing pages are server-rendered; per-match odds table is partly client-rendered and anti-bot protected - plain HTTP may miss rows.",
    },
    "bovada": {
        "kind": "api",
        "base_url": "https://www.bovada.lv/services/sports/event/v2/events",
        "confidence": 0.7,
        "requires_key": False,
        "markets": ["h2h", "spreads", "totals"],
        "notes": "Offshore book's public JSON feed; unofficial, may geo-block non-US IPs.",
    },
    "betonline": {
        "kind": "scrape",
        "base_url": "https://www.betonline.ag/sportsbook",
        "confidence": 0.5,
        "requires_key": False,
        "markets": ["h2h"],
        "notes": "No public JSON API; best-effort parse of sportsbook listing pages.",
    },
}

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
    """GET ``url`` (cached for :data:`_HTTP_CACHE_TTL`) and return the body.

    Returns ``None`` on any transport failure — never raises.
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


# ── Anti-bot / block detection (honest flagging) ────────────────────────
_BLOCK_MARKERS = (
    "cf-chl",
    "challenge-platform",
    "just a moment",
    "checking your browser",
    "attention required",
    "access denied",
    "captcha",
    "forbidden",
    "too many requests",
    "data is temporarily unavailable",
)


def _looks_blocked(text: str) -> bool:
    """True when the body smells like an anti-bot interstitial."""
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _BLOCK_MARKERS)


def _from_html(html: str) -> Any | None:
    """Parse HTML into an lxml tree; ``None`` on malformed input."""
    if not html or not html.strip():
        return None
    try:
        return _lxml_html.fromstring(html)
    except Exception:  # noqa: BLE001 - lxml raises assorted parse errors on hostile HTML
        logger.warning("sports_sources_html_parse_failed")
        return None


def _classes(element: Any) -> str:
    """Normalized class attribute of an lxml element (string or list)."""
    value = element.get("class")
    if isinstance(value, list):
        return " ".join(value)
    return " ".join(str(value or "").split())


# ── Shared record / normalization helpers ───────────────────────────────
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
    """Normalize a team name for fuzzy cross-source matching.

    Lowercases, strips punctuation and joins the remaining words so
    ``"Boston Celtics"`` -> ``"boston celtics"`` and short names match
    their full forms by substring containment.
    """
    if name is None:
        return ""
    return " ".join(re.findall(r"[a-z0-9]+", str(name).lower()))


def _split_label(label: Any) -> list[str]:
    """Split an event label like ``"Celtics @ Lakers"`` into team names."""
    if not label:
        return []
    parts = re.split(r"\s*(?:@|vs\.?|v|at|-)\s*", str(label).strip(), flags=re.I)
    teams: list[str] = []
    for part in parts:
        team = _normalize_team(part)
        if len(team) >= 3:
            teams.append(team)
    return teams


def _record_teams(record: dict[str, Any]) -> list[str]:
    """Team names of a record, preferring the home/away fields."""
    home = _normalize_team(record.get("home"))
    away = _normalize_team(record.get("away"))
    if home or away:
        return [t for t in (home, away) if len(t) >= 3]
    return _split_label(record.get("event"))


def _normalize_label(label: Any) -> str:
    """Canonical label key: lowercase alnum tokens, no separators."""
    return " ".join(sorted(set(re.findall(r"[a-z0-9]+", str(label or "").lower()))))


def _teams_contain(needles: list[str], haystack: list[str]) -> bool:
    """True when every needle team is contained in (or contains) a haystack team."""
    if not needles or not haystack:
        return False
    return all(any(needle in hm or hm in needle for hm in haystack) for needle in needles)


def same_event(record_a: dict[str, Any], record_b: dict[str, Any]) -> bool:
    """Fuzzy event identity across sources.

    Two records are the same event when their home/away teams match by
    containment in both directions (``"Celtics"`` == ``"Boston Celtics"``,
    and order-independent — ``"Celtics @ Lakers"`` == ``"Lakers vs
    Celtics"``). Records without usable team fields fall back to exact
    normalized label equality.
    """
    teams_a = _record_teams(record_a)
    teams_b = _record_teams(record_b)
    if teams_a and teams_b:
        return _teams_contain(teams_a, teams_b) and _teams_contain(teams_b, teams_a)
    label_a = _normalize_label(record_a.get("event"))
    label_b = _normalize_label(record_b.get("event"))
    return bool(label_a) and label_a == label_b


def event_matches(record: dict[str, Any], label: str | None) -> bool:
    """True when a record's event matches a target label (e.g. from odds.py)."""
    target = _split_label(label)
    if not target:
        return False
    teams = _record_teams(record)
    if not teams:
        return _normalize_label(record.get("event")) == _normalize_label(label)
    return _teams_contain(target, teams) or _teams_contain(teams, target)


def _event_id_matches(record: dict[str, Any], event_id: str | None) -> bool:
    if not event_id:
        return False
    return str(record.get("event_id") or "") == str(event_id).strip()


# ── Sport routing ───────────────────────────────────────────────────────
# Canonical sport slug -> (source-specific path, market coverage).
_ODDSPORTAL_SPORTS: dict[str, tuple[str, str]] = {
    "basketball_nba": ("basketball/usa/nba", "basketball"),
    "basketball_ncaab": ("basketball/usa/ncaa", "basketball"),
    "americanfootball_nfl": ("americanfootball/usa/nfl", "americanfootball"),
    "americanfootball_ncaaf": ("americanfootball/usa/ncaa", "americanfootball"),
    "baseball_mlb": ("baseball/usa/mlb", "baseball"),
    "icehockey_nhl": ("icehockey/usa/nhl", "icehockey"),
    "soccer_epl": ("soccer/england/premier-league", "soccer"),
    "soccer_spain_la_liga": ("soccer/spain/laliga", "soccer"),
    "soccer_germany_bundesliga": ("soccer/germany/bundesliga", "soccer"),
    "soccer_italy_serie_a": ("soccer/italy/serie-a", "soccer"),
    "tennis_atp": ("tennis/atp", "tennis"),
    "tennis_wta": ("tennis/wta", "tennis"),
    "mma_mixed_martial_arts": ("mma/ufc", "mma"),
    "boxing": ("boxing", "boxing"),
    "formula_1": ("racing/formula-1", "racing"),
    "golf_pga": ("golf/usa/pga", "golf"),
    "cricket_international_t20": ("cricket/international/t20", "cricket"),
}

_BOVADA_SPORTS: dict[str, tuple[str, str | None]] = {
    "basketball_nba": ("basketball", "nba"),
    "basketball_ncaab": ("basketball", "ncaa"),
    "americanfootball_nfl": ("football", "nfl"),
    "americanfootball_ncaaf": ("football", "ncaa"),
    "baseball_mlb": ("baseball", "mlb"),
    "icehockey_nhl": ("hockey", "nhl"),
    "soccer_epl": ("soccer", "england"),
    "soccer_spain_la_liga": ("soccer", "spain"),
    "soccer_germany_bundesliga": ("soccer", "germany"),
    "soccer_italy_serie_a": ("soccer", "italy"),
    "tennis_atp": ("tennis", None),
    "tennis_wta": ("tennis", None),
    "mma_mixed_martial_arts": ("mma", None),
    "boxing": ("boxing", None),
}

_BETONLINE_SPORTS: dict[str, tuple[str, str | None]] = {
    "basketball_nba": ("basketball", "nba"),
    "basketball_ncaab": ("basketball", "ncaa"),
    "americanfootball_nfl": ("football", "nfl"),
    "americanfootball_ncaaf": ("football", "ncaa"),
    "baseball_mlb": ("baseball", "mlb"),
    "icehockey_nhl": ("hockey", "nhl"),
    "soccer_epl": ("soccer", "england"),
    "soccer_spain_la_liga": ("soccer", "spain"),
    "soccer_germany_bundesliga": ("soccer", "germany"),
    "soccer_italy_serie_a": ("soccer", "italy"),
    "tennis_atp": ("tennis", None),
    "tennis_wta": ("tennis", None),
    "mma_mixed_martial_arts": ("mma", None),
    "boxing": ("boxing", None),
}


def source_supports(source: str, sport: str) -> bool:
    """True when a source maps the sport (canonical slug or short alias)."""
    if source not in SOURCE_NAMES or _resolve_sports is None:
        return False
    slugs = _resolve_sports(sport)
    if not slugs:
        return False
    canonical = _SPORTS[slugs[0]][0]  # aliases resolve to the canonical odds key
    if source == "oddsportal":
        return canonical in _ODDSPORTAL_SPORTS
    if source == "bovada":
        return canonical in _BOVADA_SPORTS
    if source == "betonline":
        return canonical in _BETONLINE_SPORTS
    return False


# ── OddsPortal (scrape) ─────────────────────────────────────────────────
_ODDSPORTAL_BASE = "https://www.oddsportal.com"
_MATCH_HREF_RE = re.compile(r"/([a-z0-9]+(?:-[a-z0-9]+)*)-([a-z0-9]{4,10})/?$", re.I)
_DECIMAL_OR_US_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
# Non-bookmaker summary rows that appear in the odds table.
_SKIP_ROWS = frozenset(
    {"average", "avg", "opening", "closing", "maximum", "minimum", "max", "min", "payout"}
)


def _cell_to_number(cell: str) -> float | None:
    """Parse an odds cell: decimal (2.10) or American (-110)."""
    token = cell.strip()
    if not _DECIMAL_OR_US_RE.match(token):
        return None
    if token.startswith(("+", "-")):
        if _american_to_decimal is None:
            return None
        return _american_to_decimal(token)
    value = _to_float(token)
    if value is not None and 0 < value < 1000:
        return value
    return None


def _slug_to_name(slug: str) -> str:
    """Decode a URL slug into a display name ('los-angeles-lakers' -> 'Los Angeles Lakers')."""
    return " ".join(word.capitalize() for word in re.split(r"-", slug) if word)


def _slug_pair(teams_part: str) -> tuple[str, str]:
    """Split a joined team slug into two slugs at the midpoint hyphen.

    OddsPortal match URLs join the home and away slugs without a separator
    (``los-angeles-lakers-boston-celtics-<hash>``), and team slugs themselves
    contain hyphens, so the boundary is approximate. Only used as a fallback
    when the listing's participant-name elements are not available.
    """
    tokens = teams_part.split("-")
    if len(tokens) < 2:
        return teams_part, ""
    midpoint = (len(tokens) + 1) // 2
    return "-".join(tokens[:midpoint]), "-".join(tokens[midpoint:])


def _parse_oddsportal_listing(html: str) -> list[dict[str, Any]]:
    """Parse the match listing page into [{home, away, slug, event_id}]."""
    tree = _from_html(html)
    if tree is None:
        return []
    # Participant-name anchors carry the display names; group them by href so
    # every match link gets its home + away names regardless of link order.
    names_by_href: dict[str, list[str]] = {}
    for el in tree.iter():
        if el.tag != "a":
            continue
        if "participant" not in _classes(el).lower():
            continue
        href = el.get("href") or ""
        text = _as_text(el.text_content())
        if href and text:
            names_by_href.setdefault(href, []).append(text)
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    for a in tree.iter("a"):
        href = a.get("href") or ""
        match = _MATCH_HREF_RE.search(href)
        if not match:
            continue
        teams_part, event_id = match.groups()
        if event_id in seen:
            continue
        seen.add(event_id)
        names = names_by_href.get(href, [])
        if len(names) >= 2:
            home, away = names[0], names[1]
        else:
            slug1, slug2 = _slug_pair(teams_part)
            home, away = _slug_to_name(slug1), _slug_to_name(slug2)
        events.append(
            {
                "home": _as_text(home) or "",
                "away": _as_text(away) or "",
                "slug": f"{teams_part}-{event_id}",
                "event_id": event_id,
            }
        )
    return events


def _parse_oddsportal_match(html: str) -> list[dict[str, Any]]:
    """Parse the match-detail odds table into bookmaker h2h rows.

    The first ``detail-odds`` / ``table-main`` table holds the current
    market (1X2 / moneyline). The header row tells us whether the market is
    three-way (soccer: Home/Draw/Away) or two-way (NBA: Home/Away) and which
    column is the payout, so the trailing payout number is never misread as
    an odds column.
    """
    tree = _from_html(html)
    if tree is None:
        return []
    table: Any = None
    for el in tree.iter():
        if el.tag != "table":
            continue
        cls = _classes(el)
        if "detail-odds" in cls or "table-main" in cls:
            table = el
            break
    if table is None:
        return []
    header_cells: list[str] = []
    three_way = False
    payout_index: int | None = None
    for thead in table.iter("thead"):
        for th in thead.iter("th"):
            text = _as_text(th.text_content()) or ""
            header_cells.append(text.lower())
            if text.lower() in {"x", "draw", "tie"}:
                three_way = True
            if text.lower() in {"payout", "avg", "average"}:
                payout_index = len(header_cells) - 1
        break
    if not header_cells and len(table.findall(".//tr")) > 1:
        first_row = table.findall(".//tr")[0]
        first_cells = [_as_text(td.text_content()) or "" for td in first_row.iter("td")]
        for first_cell in first_cells:
            header_cells.append(first_cell.lower())
            if first_cell.lower() in {"x", "draw", "tie"}:
                three_way = True
            if first_cell.lower() in {"payout", "avg", "average"}:
                payout_index = len(header_cells) - 1
    rows: list[dict[str, Any]] = []
    for tr in table.iter("tr"):
        cells = [_as_text(td.text_content()) for td in tr.iter("td")]
        if not cells:
            continue
        book_raw = cells[0] or (cells[1] if len(cells) > 1 else "")
        if not book_raw or _canonical_book is None:
            continue
        book = _canonical_book(book_raw)
        if not book or book in _SKIP_ROWS:
            continue
        nums: list[float] = []
        for index, cell in enumerate(cells[1:], start=1):
            if payout_index is not None and index == payout_index:
                continue
            if cell is None:
                continue
            number = _cell_to_number(cell)
            if number is not None:
                nums.append(number)
        if not nums:
            continue
        if len(nums) >= 4 and nums[-1] > 50:
            nums = nums[:-1]  # fallback: drop a trailing payout-like value
        if three_way and len(nums) >= 3:
            home_odds, draw_odds, away_odds = nums[0], nums[1], nums[2]
        elif len(nums) >= 2:
            home_odds, away_odds = nums[0], nums[1]
            draw_odds = None
        else:
            continue
        rows.append(
            {
                "book": book,
                "bookmaker": book_raw,
                "home_odds": home_odds,
                "away_odds": away_odds,
                "draw_odds": draw_odds,
            }
        )
    return rows


async def fetch_oddsportal(sport: str, limit: int = 10) -> list[dict[str, Any]]:
    """Scrape OddsPortal match listings + detail pages for one sport.

    Args:
        sport: Canonical sport key or short alias (e.g. ``"basketball_nba"``
            or ``"nba"``).
        limit: Max match-detail pages to fetch (1-25, default 10). Each page
            can yield one h2h record per bookmaker (80+ books on the site).

    Returns:
        Canonical h2h records tagged ``source="oddsportal"``; ``[]`` on any
        failure (unsupported sport, network error, anti-bot block). Never
        raises. Blocks are flagged in :func:`source_status`.
    """
    name = "oddsportal"
    start = _monotonic()
    try:
        if _resolve_sports is None:
            return []
        slugs = _resolve_sports(sport)
        if not slugs:
            logger.warning("sports_oddsportal_unsupported_sport", extra={"sport": sport})
            return []
        canonical = _SPORTS[slugs[0]][0]  # aliases resolve to the canonical odds key
        route = _ODDSPORTAL_SPORTS.get(canonical)
        if route is None:
            return []
        path, _sport_family = route
        listing_url = f"{_ODDSPORTAL_BASE}/{path}/"
        html = await _fetch_text(listing_url)
        if html is None:
            _mark(
                name, ok=False, latency_ms=int((_monotonic() - start) * 1000), error="fetch failed"
            )
            return []
        if _looks_blocked(html):
            logger.warning(
                "sports_oddsportal_blocked",
                extra={"sport": sport, "url": listing_url},
            )
            _mark(
                name,
                ok=False,
                blocked=True,
                latency_ms=int((_monotonic() - start) * 1000),
                error="anti-bot block",
            )
            return []
        events = _parse_oddsportal_listing(html)
        if not events:
            _mark(
                name,
                ok=False,
                latency_ms=int((_monotonic() - start) * 1000),
                error="no events parsed",
            )
            return []
        count = max(1, min(int(limit or 10), 25))
        detail_urls = [f"{_ODDSPORTAL_BASE}/{path}/{ev['slug']}/" for ev in events[:count]]
        bodies = await asyncio.gather(
            *(_fetch_text(url) for url in detail_urls), return_exceptions=True
        )
        records: list[dict[str, Any]] = []
        for event, body in zip(events[:count], bodies, strict=False):
            if isinstance(body, BaseException):
                continue
            if body is None or _looks_blocked(body):
                continue
            event_label = (
                _event_label(event.get("home"), event.get("away"))
                if _event_label is not None
                else None
            )
            for row in _parse_oddsportal_match(body):
                records.append(
                    _record(
                        sport=canonical,
                        event=event_label or f"{event.get('home')} - {event.get('away')}",
                        event_id=event.get("event_id"),
                        market="h2h",
                        book=row["book"],
                        bookmaker=row["bookmaker"],
                        home=event.get("home"),
                        away=event.get("away"),
                        home_odds=row["home_odds"],
                        away_odds=row["away_odds"],
                        draw_odds=row["draw_odds"],
                        last_update=None,
                        source=name,
                    )
                )
        if not records:
            _mark(
                name,
                ok=False,
                latency_ms=int((_monotonic() - start) * 1000),
                error="no odds rows parsed",
            )
        else:
            _mark(name, ok=True, latency_ms=int((_monotonic() - start) * 1000))
        return records
    except (httpx.HTTPError, OSError, ValueError):
        logger.warning("sports_oddsportal_failed", extra={"sport": sport})
        _mark(name, ok=False, latency_ms=int((_monotonic() - start) * 1000), error="fetch failed")
        return []


# ── Bovada (public JSON feed) ───────────────────────────────────────────
_BOVADA_BASE = "https://www.bovada.lv/services/sports/event/v2/events/A/description"
# Market keys on the Bovada feed.
_BOVADA_ML_KEY = {"2W-12", "2W-ML", "2W-1X2"}
_BOVADA_SPREAD_KEY = {"2W-HCAP", "2W-SP"}
_BOVADA_TOTAL_KEY = {"2W-OU", "2W-TT"}


def _bovada_side(outcome: dict[str, Any], home: str | None, away: str | None) -> str | None:
    """Map a Bovada outcome to 'home'/'away'/'over'/'under' or None."""
    otype = str(outcome.get("type") or "").upper()
    if otype == "H":
        return "home"
    if otype == "A":
        return "away"
    if otype == "O":
        return "over"
    if otype == "U":
        return "under"
    o_name = _normalize_team(outcome.get("description") or outcome.get("name") or "")
    if o_name:
        if home and o_name == _normalize_team(home):
            return "home"
        if away and o_name == _normalize_team(away):
            return "away"
    return None


def _bovada_price(outcome: dict[str, Any]) -> float | None:
    """Decimal odds from a Bovada outcome's price object."""
    price = outcome.get("price")
    if not isinstance(price, dict):
        return None
    decimal = _to_float(price.get("decimal"))
    if decimal is not None and decimal > 0:
        return round(decimal, 2)
    american = _to_float(price.get("american"))
    if american is not None and _american_to_decimal is not None:
        return _american_to_decimal(american)
    return None


def _bovada_handicap(outcome: dict[str, Any]) -> float | None:
    price = outcome.get("price")
    if not isinstance(price, dict):
        return None
    return _to_float(price.get("handicap"))


def _parse_bovada_event(event: dict[str, Any], sport: str) -> list[dict[str, Any]]:
    """Map one Bovada event onto canonical h2h/spreads/totals records."""
    competitors = event.get("competitors")
    home = away = None
    if isinstance(competitors, list):
        for comp in competitors:
            if not isinstance(comp, dict):
                continue
            comp_name = _as_text(comp.get("name"))
            if not comp_name:
                continue
            if comp.get("home") is True or str(comp.get("homeAway") or "").lower() == "home":
                home = comp_name
            elif away is None:
                away = comp_name
    if not home or not away:
        parsed = _split_label(event.get("description"))
        if len(parsed) >= 2:
            away, home = parsed[0], parsed[1]
    if not home or not away:
        return []
    event_label = (
        f"{away} @ {home}"
        if _event_label is None
        else (_event_label(home, away) or f"{away} @ {home}")
    )
    event_id = _as_text(event.get("id"))
    last_update = _as_text(event.get("lastModified")) or _as_text(event.get("startTime"))
    records: list[dict[str, Any]] = []
    groups = event.get("displayGroups")
    if not isinstance(groups, list):
        return []
    for group in groups:
        if not isinstance(group, dict):
            continue
        markets = group.get("markets")
        if not isinstance(markets, list):
            continue
        for market in markets:
            if not isinstance(market, dict):
                continue
            key = str(market.get("key") or "")
            outcomes = market.get("outcomes")
            if not isinstance(outcomes, list):
                continue
            if key in _BOVADA_ML_KEY:
                odds: dict[str, float] = {}
                for outcome in outcomes:
                    if not isinstance(outcome, dict):
                        continue
                    side = _bovada_side(outcome, home, away)
                    price = _bovada_price(outcome)
                    if side in {"home", "away"} and price is not None:
                        odds[side] = price
                if odds:
                    records.append(
                        _record(
                            sport=sport,
                            event=event_label,
                            event_id=event_id,
                            market="h2h",
                            book="bovada",
                            bookmaker="Bovada",
                            home=home,
                            away=away,
                            home_odds=odds.get("home"),
                            away_odds=odds.get("away"),
                            last_update=last_update,
                            source="bovada",
                        )
                    )
            elif key in _BOVADA_SPREAD_KEY:
                spread_odds: dict[str, float] = {}
                line: float | None = None
                for outcome in outcomes:
                    if not isinstance(outcome, dict):
                        continue
                    side = _bovada_side(outcome, home, away)
                    price = _bovada_price(outcome)
                    if side in {"home", "away"} and price is not None:
                        spread_odds[side] = price
                        if line is None:
                            line = _bovada_handicap(outcome)
                if spread_odds:
                    records.append(
                        _record(
                            sport=sport,
                            event=event_label,
                            event_id=event_id,
                            market="spreads",
                            book="bovada",
                            bookmaker="Bovada",
                            home=home,
                            away=away,
                            home_odds=spread_odds.get("home"),
                            away_odds=spread_odds.get("away"),
                            spread=line,
                            last_update=last_update,
                            source="bovada",
                        )
                    )
            elif key in _BOVADA_TOTAL_KEY:
                over_price = under_price = None
                total_line: float | None = None
                for outcome in outcomes:
                    if not isinstance(outcome, dict):
                        continue
                    side = _bovada_side(outcome, home, away)
                    price = _bovada_price(outcome)
                    if price is None:
                        continue
                    if side == "over":
                        over_price = price
                        total_line = _bovada_handicap(outcome)
                    elif side == "under":
                        under_price = price
                if over_price is not None or under_price is not None:
                    records.append(
                        _record(
                            sport=sport,
                            event=event_label,
                            event_id=event_id,
                            market="totals",
                            book="bovada",
                            bookmaker="Bovada",
                            home=home,
                            away=away,
                            home_odds=over_price,
                            away_odds=under_price,
                            total=total_line,
                            last_update=last_update,
                            source="bovada",
                        )
                    )
    return records


async def fetch_bovada(sport: str) -> list[dict[str, Any]]:
    """Fetch one sport's odds from Bovada's public JSON feed.

    Args:
        sport: Canonical sport key or short alias (e.g. ``"basketball_nba"``).

    Returns:
        Canonical h2h/spreads/totals records tagged ``source="bovada"``;
        ``[]`` on any failure (unsupported sport, network error, geo-block).
        Never raises.
    """
    name = "bovada"
    start = _monotonic()
    try:
        if _resolve_sports is None:
            return []
        slugs = _resolve_sports(sport)
        if not slugs:
            return []
        canonical = _SPORTS[slugs[0]][0]  # aliases resolve to the canonical odds key
        route = _BOVADA_SPORTS.get(canonical)
        if route is None:
            return []
        sport_slug, league = route
        url = f"{_BOVADA_BASE}/{sport_slug}"
        if league:
            url = f"{url}/{league}"
        payload = await _fetch_json(url)
        if payload is None:
            _mark(
                name, ok=False, latency_ms=int((_monotonic() - start) * 1000), error="fetch failed"
            )
            return []
        if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
            _mark(
                name,
                ok=False,
                latency_ms=int((_monotonic() - start) * 1000),
                error="unexpected payload",
            )
            return []
        events = payload[0].get("events")
        if not isinstance(events, list):
            _mark(name, ok=False, latency_ms=int((_monotonic() - start) * 1000), error="no events")
            return []
        records: list[dict[str, Any]] = []
        for event in events:
            if isinstance(event, dict):
                records.extend(_parse_bovada_event(event, canonical))
        if not records:
            _mark(
                name,
                ok=False,
                latency_ms=int((_monotonic() - start) * 1000),
                error="no odds parsed",
            )
        else:
            _mark(name, ok=True, latency_ms=int((_monotonic() - start) * 1000))
        return records
    except (httpx.HTTPError, OSError, ValueError):
        logger.warning("sports_bovada_failed", extra={"sport": sport})
        _mark(name, ok=False, latency_ms=int((_monotonic() - start) * 1000), error="fetch failed")
        return []


# ── BetOnline (listing-page scrape, no public API) ──────────────────────
_BETONLINE_BASE = "https://www.betonline.ag/sportsbook"
_GAME_HREF_RE = re.compile(r"/sportsbook/[^/]+/[^/]+/game/(\d+)", re.I)
_US_ODDS_RE = re.compile(r"[+-]\d{3,4}\b")
_TEAM_CLASS_RE = re.compile(r"team|participant|name", re.I)


def _container_text(el: Any) -> str:
    try:
        return el.text_content() or ""
    except Exception:  # noqa: BLE001 - lxml text access on odd nodes
        return ""


def _team_names_from_container(container: Any) -> list[str]:
    """Best-effort team names from a game row container."""
    candidates: list[str] = []
    for el in container.iter():
        cls = _classes(el)
        if not _TEAM_CLASS_RE.search(cls):
            continue
        text = _as_text(el.text_content())
        if text and _US_ODDS_RE.search(text) is None:
            candidates.append(text)
    if len(candidates) >= 2:
        return candidates[:2]
    # Fallback: the two longest non-odds text nodes in the row.
    texts: list[str] = []
    for node in container.itertext():
        node_text = _as_text(node)
        if node_text and _US_ODDS_RE.search(node_text) is None and 3 <= len(node_text) <= 40:
            texts.append(node_text)
    texts = sorted(set(texts), key=len, reverse=True)
    return texts[:2]


def _parse_betonline_html(html: str, sport: str) -> list[dict[str, Any]]:
    """Parse the sportsbook listing page into h2h records (best-effort)."""
    tree = _from_html(html)
    if tree is None:
        return []
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for a in tree.iter("a"):
        href = a.get("href") or ""
        match = _GAME_HREF_RE.search(href)
        if not match:
            continue
        game_id = match.group(1)
        if game_id in seen:
            continue
        seen.add(game_id)
        container: Any = a
        for _depth in range(8):
            parent = container.getparent()
            if parent is None:
                break
            container = parent
        container_text = _container_text(container)
        odds_tokens = _US_ODDS_RE.findall(container_text)
        teams = _team_names_from_container(container)
        if len(teams) < 2 or len(odds_tokens) < 2:
            continue
        away, home = teams[0], teams[1]  # sportsbook convention: away first
        away_odds = (
            _american_to_decimal(odds_tokens[0]) if _american_to_decimal is not None else None
        )
        home_odds = (
            _american_to_decimal(odds_tokens[1]) if _american_to_decimal is not None else None
        )
        if away_odds is None and home_odds is None:
            continue
        event_label = (
            f"{away} @ {home}"
            if _event_label is None
            else (_event_label(home, away) or f"{away} @ {home}")
        )
        records.append(
            _record(
                sport=sport,
                event=event_label,
                event_id=game_id,
                market="h2h",
                book="betonline",
                bookmaker="BetOnline",
                home=home,
                away=away,
                home_odds=home_odds,
                away_odds=away_odds,
                last_update=None,
                source="betonline",
            )
        )
    return records


def _parse_betonline_embedded_json(html: str, sport: str) -> list[dict[str, Any]]:
    """Parse a ``window.__INITIAL_STATE__``-style JSON blob, if embedded."""
    match = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});", html, re.S)
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    events: list[dict[str, Any]] = []

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            if "gameId" in node and ("homeTeam" in node or "gameData" in node):
                events.append(node)
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(data)
    records: list[dict[str, Any]] = []
    for event in events:
        game_id = _as_text(event.get("gameId"))
        home = _as_text(event.get("homeTeam"))
        away = _as_text(event.get("awayTeam"))
        if not home or not away or _american_to_decimal is None:
            continue
        game_data = event.get("gameData")
        if not isinstance(game_data, list):
            continue
        home_odds = away_odds = None
        for period in game_data:
            if not isinstance(period, dict):
                continue
            line_type = str(period.get("lineType") or "")
            line_dict = period.get("lineDict")
            if not isinstance(line_dict, dict):
                continue
            money = line_dict.get("MoneyLine")
            if not isinstance(money, dict):
                continue
            value = _as_text(money.get("decimalLine")) or _as_text(money.get("line"))
            if line_type == "AwayLine":
                away_odds = _to_float(value)
            elif line_type == "HomeLine":
                home_odds = _to_float(value)
        if home_odds is None and away_odds is None:
            continue
        event_label = (
            f"{away} @ {home}"
            if _event_label is None
            else (_event_label(home, away) or f"{away} @ {home}")
        )
        records.append(
            _record(
                sport=sport,
                event=event_label,
                event_id=game_id,
                market="h2h",
                book="betonline",
                bookmaker="BetOnline",
                home=home,
                away=away,
                home_odds=home_odds,
                away_odds=away_odds,
                last_update=_as_text(event.get("wagerCutOff")),
                source="betonline",
            )
        )
    return records


async def fetch_betonline(sport: str) -> list[dict[str, Any]]:
    """Fetch one sport's odds from BetOnline's sportsbook listing pages.

    BetOnline publishes no public JSON API, so this is a best-effort parse
    of the server-rendered listing HTML (game links + inline US odds) and of
    an embedded ``window.__INITIAL_STATE__`` blob when present.

    Args:
        sport: Canonical sport key or short alias (e.g. ``"basketball_nba"``).

    Returns:
        Canonical h2h records tagged ``source="betonline"``; ``[]`` on any
        failure. Never raises.
    """
    name = "betonline"
    start = _monotonic()
    try:
        if _resolve_sports is None:
            return []
        slugs = _resolve_sports(sport)
        if not slugs:
            return []
        canonical = _SPORTS[slugs[0]][0]  # aliases resolve to the canonical odds key
        route = _BETONLINE_SPORTS.get(canonical)
        if route is None:
            return []
        sport_slug, league = route
        url = f"{_BETONLINE_BASE}/{sport_slug}"
        if league:
            url = f"{url}/{league}"
        html = await _fetch_text(url)
        if html is None:
            _mark(
                name, ok=False, latency_ms=int((_monotonic() - start) * 1000), error="fetch failed"
            )
            return []
        if _looks_blocked(html):
            _mark(
                name,
                ok=False,
                blocked=True,
                latency_ms=int((_monotonic() - start) * 1000),
                error="anti-bot block",
            )
            return []
        records = _parse_betonline_embedded_json(html, canonical)
        if not records:
            records = _parse_betonline_html(html, canonical)
        if not records:
            _mark(
                name,
                ok=False,
                latency_ms=int((_monotonic() - start) * 1000),
                error="no odds parsed",
            )
        else:
            _mark(name, ok=True, latency_ms=int((_monotonic() - start) * 1000))
        return records
    except (httpx.HTTPError, OSError, ValueError):
        logger.warning("sports_betonline_failed", extra={"sport": sport})
        _mark(name, ok=False, latency_ms=int((_monotonic() - start) * 1000), error="fetch failed")
        return []


# ── Cross-source merge ──────────────────────────────────────────────────
_SHARP_BOOKS = frozenset({"pinnacle"})


def _source_rank(record: dict[str, Any]) -> int:
    """Priority index of a record's source (lower = preferred)."""
    source = str(record.get("source") or "").strip().lower()
    try:
        return SOURCE_PRIORITY.index(source)
    except ValueError:
        return len(SOURCE_PRIORITY)


def _ts_float(value: Any) -> float:
    """ISO timestamp -> epoch seconds; missing/unparseable -> -inf."""
    if not value:
        return float("-inf")
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return float("-inf")


def _priority_key(record: dict[str, Any], index: int) -> tuple[Any, ...]:
    """Sort key: sharpest book first, then source rank, then newer update."""
    book = str(record.get("book") or "").strip().lower()
    sharp = 0 if book in _SHARP_BOOKS else 1
    return (sharp, _source_rank(record), -_ts_float(record.get("last_update")), index)


def _conflicts(record_a: dict[str, Any], record_b: dict[str, Any]) -> bool:
    """True when two records describe the same (event, market, book)."""
    if str(record_a.get("market") or "") != str(record_b.get("market") or ""):
        return False
    if str(record_a.get("book") or "") != str(record_b.get("book") or ""):
        return False
    return same_event(record_a, record_b)


def merge_odds(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedupe odds records across sources.

    Records are grouped by (event, market, book); on a conflict (the same
    event+market+book reported by two sources with different lines) the
    winner is:

    1. the sharpest book (Pinnacle beats everyone),
    2. the highest-confidence source (:data:`SOURCE_PRIORITY` order),
    3. the most recent ``last_update``,
    4. the earliest position in the input.

    Non-conflicting records (different books, different events) are all
    kept, and output preserves the input order. Each surviving record keeps
    its original ``source`` tag.
    """
    keyed: list[tuple[int, dict[str, Any]]] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        keyed.append((index, record))
    ordered = sorted(keyed, key=lambda pair: _priority_key(pair[1], pair[0]))
    accepted: list[tuple[int, dict[str, Any]]] = []
    for index, record in ordered:
        if any(_conflicts(record, acc) for _, acc in accepted):
            continue
        accepted.append((index, record))
    accepted.sort(key=lambda pair: pair[0])
    return [record for _, record in accepted]
