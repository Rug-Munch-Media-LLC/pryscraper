"""OddsPortal scrape fetcher for the multi-source sports odds feed.

OddsPortal (``www.oddsportal.com``) is a consumer odds-comparison site
with 80+ bookmakers across every sport. Match-listing pages are
server-rendered HTML; the per-match bookmaker odds table is partly
client-rendered and the site runs anti-bot protection, so plain HTTP only
sees odds rows when the server includes them. Blocks are detected and
flagged honestly (never silently treated as "no odds").

Transport (fetch/cache/health) lives in :mod:`sports_data.sources` and is
reached through a late module handle so test monkeypatches keep working.

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
import re
from typing import Any

import httpx

from datasets.sports_data.odds_common import (
    _SPORTS as _SPORTS,
    _american_to_decimal as _american_to_decimal,
    _canonical_book as _canonical_book,
    _event_label as _event_label,
    _resolve_sports as _resolve_sports,
)
from datasets.sports_data.sources_common import (
    _as_text,
    _classes,
    _from_html,
    _looks_blocked,
    _to_float,
)

logger = logging.getLogger(__name__)

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
        raises. Blocks are flagged in the source registry's live status.
    """
    from datasets.sports_data import sources as _base

    name = "oddsportal"
    start = _base._monotonic()
    try:
        if _resolve_sports is None:
            return []
        slugs = _resolve_sports(sport)
        if not slugs:
            logger.warning("sports_oddsportal_unsupported_sport", extra={"sport": sport})
            return []
        canonical = _SPORTS[slugs[0]][0]  # aliases resolve to the canonical odds key
        route = _base._ODDSPORTAL_SPORTS.get(canonical)
        if route is None:
            return []
        path, _sport_family = route
        listing_url = f"{_ODDSPORTAL_BASE}/{path}/"
        html = await _base._fetch_text(listing_url)
        if html is None:
            _base._mark(
                name,
                ok=False,
                latency_ms=int((_base._monotonic() - start) * 1000),
                error="fetch failed",
            )
            return []
        if _looks_blocked(html):
            logger.warning(
                "sports_oddsportal_blocked",
                extra={"sport": sport, "url": listing_url},
            )
            _base._mark(
                name,
                ok=False,
                blocked=True,
                latency_ms=int((_base._monotonic() - start) * 1000),
                error="anti-bot block",
            )
            return []
        events = _parse_oddsportal_listing(html)
        if not events:
            _base._mark(
                name,
                ok=False,
                latency_ms=int((_base._monotonic() - start) * 1000),
                error="no events parsed",
            )
            return []
        count = max(1, min(int(limit or 10), 25))
        detail_urls = [f"{_ODDSPORTAL_BASE}/{path}/{ev['slug']}/" for ev in events[:count]]
        bodies = await asyncio.gather(
            *(_base._fetch_text(url) for url in detail_urls), return_exceptions=True
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
                    _base._record(
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
            _base._mark(
                name,
                ok=False,
                latency_ms=int((_base._monotonic() - start) * 1000),
                error="no odds rows parsed",
            )
        else:
            _base._mark(name, ok=True, latency_ms=int((_base._monotonic() - start) * 1000))
        return records
    except (httpx.HTTPError, OSError, ValueError):
        logger.warning("sports_oddsportal_failed", extra={"sport": sport})
        _base._mark(
            name,
            ok=False,
            latency_ms=int((_base._monotonic() - start) * 1000),
            error="fetch failed",
        )
        return []
