"""Public betting-percentage intel — money % / ticket % / steam moves.

OddsJam sells this exact feed for ~$1.5k/month. We approximate it with three
best-effort sources, in priority order, all async and never-raising:

1. **Configured JSON feed** (``PRY_BETTING_PERCENT_FEED``) — an
   Odds-Shark/Action-style per-event endpoint returning
   ``{home_money_pct, away_money_pct, home_ticket_pct, away_ticket_pct,
   steam_moves}`` (alternate key spellings are tolerated). This is the
   reliable path: point the env var at a feed you have rights to
   (OddsShark/Action/partner API). The URL may contain a ``{event_id}``
   placeholder; otherwise the event id is appended as a path segment.
2. **The Odds API comparison** (only if present) — some normalized feeds
   embed money/ticket percentages inside the event payload; we scan the
   ``sports_data.odds.get_event_odds`` comparison for such fields. The free
   tier does **not** include them today, so this path is defensive.
3. **Public odds page** (``PRY_BETTING_PERCENT_PAGE``, default a Covers /
   Odds-Shark-style moneyline page) — regex-extracts embedded
   ``"moneyPct"`` / ``"ticketPct"`` style JSON tokens. The live sites are
   JS-rendered, so this fallback is genuinely best-effort.

[REVIEW] Feasibility flag: there is **no stable no-auth public API** for
Odds-Shark/Action-style money percentages as of 2026 — Odds Shark now
redirects to Covers.com and the public pages render percentages client-side,
while Action Network's feed requires auth. The JSON-feed path (1) is the one
that works reliably once configured; paths (2) and (3) exist so the function
still degrades gracefully and never fabricates data. When nothing parseable
is found, :func:`get_betting_percentages` returns ``{}`` — it never invents
percentages.

Contract
--------
* :func:`get_betting_percentages` — async, never raises, returns a ``dict``
  with ``home_money_pct`` / ``away_money_pct`` / ``home_ticket_pct`` /
  ``away_ticket_pct`` / ``steam_moves`` (money and ticket pairs normalized
  to sum 100 when both sides are present), or ``{}`` on failure.

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
import os
import re
from typing import Any
from urllib.parse import quote

import httpx

from pry.engine.retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

_FEED_ENV = "PRY_BETTING_PERCENT_FEED"
_PAGE_ENV = "PRY_BETTING_PERCENT_PAGE"
# Odds Shark redirects to Covers; the public NBA moneyline page is the
# closest no-auth proxy for money/ticket percentages (JS-rendered).
_DEFAULT_PAGE = "https://www.covers.com/sport/basketball/nba/odds"

_TIMEOUT = httpx.Timeout(10.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=1,
    base_delay=0.1,
    max_delay=0.4,
    retryable_exceptions=(httpx.HTTPError,),
)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; pryscraper-sports/1.0; "
        "+https://git.rugmunch.io/RugMunchMedia/pryscraper)"
    ),
    "Accept": "application/json,text/html",
}

# Alternate key spellings tolerated from a JSON feed.
_MONEY_KEYS = (
    "home_money_pct",
    "away_money_pct",
    "money_home_pct",
    "money_away_pct",
    "homeMoneyPct",
    "awayMoneyPct",
    "home_money_percent",
    "away_money_percent",
)
_TICKET_KEYS = (
    "home_ticket_pct",
    "away_ticket_pct",
    "ticket_home_pct",
    "ticket_away_pct",
    "homeTicketPct",
    "awayTicketPct",
    "home_ticket_percent",
    "away_ticket_percent",
)
_STEAM_KEYS = ("steam_moves", "steamMoves", "steam_count", "steamMovesCount")

# Embedded-JSON token patterns for the HTML fallback, e.g.
# {"homeMoneyPct": 62.0, "awayTicketPct": 48} inside a page script block.
_MONEY_TOKEN = re.compile(r'"([^"]*(?:home|away)[^"]*(?:money|Money)[^"]*)"\s*:\s*(\d+(?:\.\d+)?)')
_TICKET_TOKEN = re.compile(
    r'"([^"]*(?:home|away)[^"]*(?:ticket|Ticket)[^"]*)"\s*:\s*(\d+(?:\.\d+)?)'
)

# Guarded import: sports_data.odds is owned by a parallel agent and may not
# exist yet when this module is first imported.
try:
    from datasets.sports_data.odds import get_event_odds as _get_event_odds
except ImportError:  # pragma: no cover - parallel build guard
    _get_event_odds = None  # type: ignore[assignment]


def _to_float(value: Any) -> float | None:
    """Coerce a JSON value to float/None ('' / garbage -> None)."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _feed_url(event_id: str) -> str:
    """Build the configured feed URL for one event ('' when unset)."""
    raw = os.environ.get(_FEED_ENV, "").strip()
    if not raw:
        return ""
    if "{event_id}" in raw:
        return raw.replace("{event_id}", quote(event_id))
    return f"{raw.rstrip('/')}/{quote(event_id)}"


def _page_url(event_id: str, sport: str) -> str:
    """Build the public page URL for one event ('' when disabled)."""
    raw = os.environ.get(_PAGE_ENV, "").strip()
    base = raw or _DEFAULT_PAGE
    if "{event_id}" in base:
        return base.replace("{event_id}", quote(event_id))
    return f"{base.rstrip('/')}#event={quote(event_id)}"


async def _fetch_text(url: str) -> str | None:
    """GET ``url`` and return the body text (never raises)."""

    async def _one() -> str:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


def _parse_feed_json(payload: Any) -> dict[str, Any] | None:
    """Map a JSON feed payload onto the canonical percentage dict."""
    if not isinstance(payload, dict):
        return None
    home_money = _pick(payload, *[k for k in _MONEY_KEYS if "home" in k])
    away_money = _pick(payload, *[k for k in _MONEY_KEYS if "away" in k])
    home_ticket = _pick(payload, *[k for k in _TICKET_KEYS if "home" in k])
    away_ticket = _pick(payload, *[k for k in _TICKET_KEYS if "away" in k])
    steam = _pick(payload, *_STEAM_KEYS)
    return _build_result(
        home_money=home_money,
        away_money=away_money,
        home_ticket=home_ticket,
        away_ticket=away_ticket,
        steam_moves=steam,
    )


def _pick(mapping: dict[str, Any], *keys: str) -> float | None:
    """Return the first numeric value found under any of ``keys``."""
    for key in keys:
        value = _to_float(mapping.get(key))
        if value is not None:
            return value
    return None


def _normalize_pair(home: float | None, away: float | None) -> tuple[float | None, float | None]:
    """Normalize a (home, away) percentage pair to sum 100."""
    if home is None and away is None:
        return None, None
    home = home if home is not None else 0.0
    away = away if away is not None else 0.0
    total = home + away
    if total <= 0:
        return None, None
    return round(home / total * 100.0, 1), round(away / total * 100.0, 1)


def _build_result(
    *,
    home_money: float | None,
    away_money: float | None,
    home_ticket: float | None,
    away_ticket: float | None,
    steam_moves: float | None,
) -> dict[str, Any] | None:
    """Compose the canonical dict; None when no useful data exists."""
    home_money, away_money = _normalize_pair(home_money, away_money)
    home_ticket, away_ticket = _normalize_pair(home_ticket, away_ticket)
    if home_money is None and home_ticket is None:
        return None
    steam = int(steam_moves) if steam_moves is not None and steam_moves >= 0 else 0
    return {
        "home_money_pct": home_money,
        "away_money_pct": away_money,
        "home_ticket_pct": home_ticket,
        "away_ticket_pct": away_ticket,
        "steam_moves": steam,
    }


def _collect_percent_tokens(node: Any, tokens: dict[str, list[float]]) -> None:
    """Walk a JSON structure collecting money/ticket token values."""
    if isinstance(node, dict):
        for key, value in node.items():
            text_key = str(key)
            numeric = _to_float(value)
            if numeric is not None:
                if re.search(r"money|handle", text_key, re.IGNORECASE):
                    tokens.setdefault("money", []).append(numeric)
                elif re.search(r"ticket", text_key, re.IGNORECASE):
                    tokens.setdefault("ticket", []).append(numeric)
            else:
                _collect_percent_tokens(value, tokens)
    elif isinstance(node, list):
        for item in node:
            _collect_percent_tokens(item, tokens)


def _from_tokens(tokens: dict[str, list[float]]) -> dict[str, Any] | None:
    """Best-effort side assignment from collected money/ticket tokens."""
    money = tokens.get("money") or []
    ticket = tokens.get("ticket") or []
    result: dict[str, Any] = {}
    if money:
        result["home_money_pct"] = money[0]
        result["away_money_pct"] = money[1] if len(money) > 1 else 100.0 - money[0]
    if ticket:
        result["home_ticket_pct"] = ticket[0]
        result["away_ticket_pct"] = ticket[1] if len(ticket) > 1 else 100.0 - ticket[0]
    if not result:
        return None
    return _build_result(
        home_money=result.get("home_money_pct"),
        away_money=result.get("away_money_pct"),
        home_ticket=result.get("home_ticket_pct"),
        away_ticket=result.get("away_ticket_pct"),
        steam_moves=None,
    )


async def _from_json_feed(event_id: str) -> dict[str, Any] | None:
    """Source 1: configured Odds-Shark/Action-style JSON feed."""
    url = _feed_url(event_id)
    if not url:
        return None
    text = await _fetch_text(url)
    if not text:
        return None
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return None
    return _parse_feed_json(payload)


async def _from_event_comparison(event_id: str) -> dict[str, Any] | None:
    """Source 2: betting percentages embedded in the odds comparison."""
    if _get_event_odds is None:
        return None
    try:
        comparison = await _get_event_odds(event_id)
    except Exception:
        logger.exception("sports_betting_pct_odds_failed", extra={"event_id": event_id})
        return None
    if not comparison:
        return None
    tokens: dict[str, list[float]] = {}
    _collect_percent_tokens(comparison, tokens)
    return _from_tokens(tokens)


def _from_html(html: str) -> dict[str, Any] | None:
    """Source 3: regex money/ticket tokens from a public odds page."""
    money: dict[str, float] = {}
    ticket: dict[str, float] = {}
    for match in _MONEY_TOKEN.finditer(html):
        key, value = match.group(1), match.group(2)
        try:
            numeric = float(value)
        except ValueError:  # pragma: no cover - regex guarantees digits
            continue
        if "away" in key.lower() and "away" not in money:
            money["away"] = numeric
        elif "home" in key.lower() and "home" not in money:
            money["home"] = numeric
    for match in _TICKET_TOKEN.finditer(html):
        key, value = match.group(1), match.group(2)
        try:
            numeric = float(value)
        except ValueError:  # pragma: no cover - regex guarantees digits
            continue
        if "away" in key.lower() and "away" not in ticket:
            ticket["away"] = numeric
        elif "home" in key.lower() and "home" not in ticket:
            ticket["home"] = numeric
    if not money and not ticket:
        return None
    return _build_result(
        home_money=money.get("home"),
        away_money=money.get("away"),
        home_ticket=ticket.get("home"),
        away_ticket=ticket.get("away"),
        steam_moves=None,
    )


async def _from_page(event_id: str, sport: str) -> dict[str, Any] | None:
    """Source 3 wrapper: fetch the public page and regex-parse it."""
    text = await _fetch_text(_page_url(event_id, sport))
    if not text:
        return None
    return _from_html(text)


async def get_betting_percentages(event_id: str, sport: str = "nba") -> dict[str, Any]:
    """Fetch public betting-percentage intel for one event (never raises).

    Args:
        event_id: Event id to look up.
        sport: Sport used to pick the public page fallback (default ``nba``).

    Returns:
        A dict with ``home_money_pct`` / ``away_money_pct`` /
        ``home_ticket_pct`` / ``away_ticket_pct`` / ``steam_moves``, or
        ``{}`` when no source yields parseable data (never fabricates).
    """
    target_id = str(event_id or "").strip()
    if not target_id:
        return {}
    result = await _from_json_feed(target_id)
    if result is not None:
        return result
    result = await _from_event_comparison(target_id)
    if result is not None:
        return result
    result = await _from_page(target_id, str(sport or "nba").strip().lower())
    if result is not None:
        return result
    return {}
