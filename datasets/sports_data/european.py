"""European / globally-reachable sportsbook odds fetchers for Pry.

Covers the books that are reachable without a US geo-IP, prioritizing the
high-value sharp/consensus books:

* **Pinnacle** — the sharpest book. Uses the semi-public guest JSON API
  (``guest.api.pinnacle.com/v1``: ``/leagues``, ``/fixtures``, ``/odds``),
  no auth, decimal odds; the sharp line for CLV / no-vig consensus.
* **Marathonbet** — server-rendered coupon pages (decimal odds rows).
* **1xBet** — internal ``LineFeed`` JSON endpoint (gzip/base64 payload).
* **Betfair** — public read-only Exchange endpoint
  (``/www/sports/exchange/readonly/v1/bymarket``) plus market-ID discovery
  from the exchange pages. No login required.
* **Betway, 10Bet, SBOBet, Dafabet, 12Bet, W88** — best-effort embedded
  state / HTML row parsing; several are JS-heavy or hard-geo-blocked, and
  plain HTTP often returns no odds — that is flagged honestly.

Transport: Pry's own httpx + stealth headers, with a Webshare proxy retry
(``WEBSHARE_PROXY_LIST``) when a direct request looks geo-blocked (shared
with :mod:`sports_data.offshore`).

Contract
--------
* :func:`fetch_european_odds` aggregates every per-book fetcher and never
  raises — it returns ``[]`` on any failure. One dead book never affects
  the others.
* Every record follows the canonical odds schema from
  :mod:`sports_data.odds` and is tagged ``source="european"``.

Free-API terms: Pinnacle guest API and the Betfair read-only endpoint are
undocumented public feeds; Marathonbet/1xBet pages are consumer pages —
scrape politely, expect layout drift and blocks.

Module layout (split for size): registry/health/status helpers in
:mod:`datasets.sports_data.european_common`, Pinnacle in
:mod:`european_pinnacle`, Marathonbet/1xBet/Betfair in
:mod:`european_exchange`, generic books in :mod:`european_generic` — all
re-exported here.

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
from typing import Any

import httpx

from datasets.sports_data.european_common import (  # noqa: F401 - re-export
    _BOOK_HEALTH,
    _EUROPEAN_SPORTS,
    EUROPEAN_BOOK_ORDER,
    EUROPEAN_BOOKS,
    _canonical_sport,
    _mark_book,
    available_books,
    book_status,
    book_supports,
)
from datasets.sports_data.european_exchange import (
    fetch_1xbet,
    fetch_betfair,
    fetch_marathonbet,
)
from datasets.sports_data.european_generic import (  # noqa: F401 - re-export
    fetch_10bet,
    fetch_12bet,
    fetch_betway,
    fetch_dafabet,
    fetch_sbobet,
    fetch_w88,
)
from datasets.sports_data.european_pinnacle import fetch_pinnacle

logger = logging.getLogger(__name__)

# ── Sibling registry annotation (sports_data.books) ─────────────────────
# Guarded reuse of the sibling BOOKS registry (owned by another agent).
# Kept in this module so tests can monkeypatch ``european._SIBLING_BOOKS``.
try:
    import datasets.sports_data.books as _sibling_books

    _SIBLING_BOOKS: dict[str, dict[str, Any]] | None = getattr(_sibling_books, "BOOKS", None)
except ImportError:  # pragma: no cover - sibling module may not exist yet
    _SIBLING_BOOKS = None

# My slugs that don't match the sibling's book ids / display names directly.
_SIBLING_ALIASES: dict[str, str] = {"betway": "betway-uk"}


def _sibling_entry(book: str) -> dict[str, Any] | None:
    """Sibling registry entry for a book slug (by id, display name, alias)."""
    if not _SIBLING_BOOKS:
        return None
    direct = _SIBLING_BOOKS.get(book) or _SIBLING_BOOKS.get(_SIBLING_ALIASES.get(book, ""))
    if isinstance(direct, dict):
        return direct
    norm = "".join(ch for ch in book.lower() if ch.isalnum())
    for entry in _SIBLING_BOOKS.values():
        if not isinstance(entry, dict):
            continue
        name_key = "".join(ch for ch in str(entry.get("name") or "").lower() if ch.isalnum())
        if name_key == norm:
            return entry
    return None


async def fetch_european_odds(sport: str, limit: int = 50) -> list[dict[str, Any]]:
    """Aggregate odds for one sport across every European book.

    Runs all per-book fetchers concurrently. One dead or geo-blocked book
    never affects the others.

    Args:
        sport: Canonical sport key or short alias (e.g. ``"basketball_nba"``
            or ``"nba"``).
        limit: Max records to parse per book (matches the per-source cap
            convention in ``sports_data.sources``).

    Returns:
        Canonical odds records from every reachable book; ``[]`` on any
        failure. Never raises.
    """
    try:
        fetchers: list[Any] = [_fetch_book(sport, book, limit) for book in EUROPEAN_BOOK_ORDER]
        results = await asyncio.gather(*fetchers, return_exceptions=True)
    except (httpx.HTTPError, OSError, ValueError):
        return []
    records: list[dict[str, Any]] = []
    for result in results:
        if isinstance(result, BaseException):
            continue
        if not isinstance(result, list):
            continue
        records.extend(record for record in result if isinstance(record, dict))
    return records


# Book-specific dispatch used by the aggregate (each never raises).
async def _fetch_book(sport: str, book: str, limit: int) -> list[dict[str, Any]]:
    if book == "pinnacle":
        return await fetch_pinnacle(sport, limit)
    if book == "marathonbet":
        return await fetch_marathonbet(sport, limit)
    if book == "1xbet":
        return await fetch_1xbet(sport, limit)
    if book == "betfair":
        return await fetch_betfair(sport, limit)
    from datasets.sports_data.european_generic import _fetch_generic_book

    return await _fetch_generic_book(sport, book, limit)
