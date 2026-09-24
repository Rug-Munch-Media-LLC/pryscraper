"""Compatibility facade for US sportsbook fetching."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from datasets.sports_data.us_books.registry import (
    _BR_GROUP_IDS,
    _DK_CATEGORY_IDS,
    _FD_EVENT_GROUP_IDS,
    _HEALTH as _HEALTH,
    _PB_COMPETITION_IDS,
    _US_BOOK_IDS as _US_BOOK_IDS,
    US_BOOKS,
    _mark,
    book_status as book_status,
)
from datasets.sports_data.us_books.transport import (
    _SPORTS as _SPORTS,
    _cache_enabled as _cache_enabled,
    _clear_cache as _clear_cache,
    _fetch_json_via_proxy as _transport_fetch_json_via_proxy,
    _fetch_uncached_via_proxy as _fetch_uncached_via_proxy,
    _looks_blocked as _looks_blocked,
    _monotonic as _monotonic,
    _resolve_sports as _resolve_sports,
    _stealth_headers as _stealth_headers,
    fetch_via_tor,
    next_webshare_proxy,
)

logger = logging.getLogger(__name__)


async def _fetch_json_via_proxy(url: str, referer: str) -> Any | None:
    """Facade wrapper preserving legacy transport monkeypatch seams."""
    return await _transport_fetch_json_via_proxy(
        url,
        referer,
        proxy_provider=lambda: next_webshare_proxy,
        tor_provider=lambda: fetch_via_tor,
    )


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


from datasets.sports_data.us_books_parsers import (  # noqa: E402
    _parse_dk_eventgroup,
    _parse_fanduel_eventgroup,
    _parse_generic_events,
    _parse_pointsbet_events,
)

_PARSERS: dict[str, Any] = {
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

from datasets.sports_data.us_books_api import (  # noqa: E402,F401
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
