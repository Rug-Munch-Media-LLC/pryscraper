"""Offshore sportsbook odds fetchers for Pry (reachable without a US geo-IP).

Thin re-export facade — the implementation lives in focused sibling
modules:

* :mod:`sports_data.offshore_books` — book registry, sport routing, live
  availability tracking (:data:`OFFSHORE_BOOKS`, :func:`book_status`).
* :mod:`sports_data.offshore_transport` — geo-aware HTTP transport with
  Webshare proxy fallback (:func:`_fetch_text_geo`, :func:`_fetch_json_geo`).
* :mod:`sports_data.offshore_parsers` — generic embedded-state and
  decimal-rows parsers for standalone books.
* :mod:`sports_data.offshore_fetchers` — per-book fetch pipeline, the
  public ``fetch_<book>()`` fetchers, and the :func:`fetch_offshore_odds`
  aggregator.

Books covered (13 new + the existing Bovada/BetOnline fetchers reused):

* BookMaker-group brands share the BetOnline platform markup (game links
  ``/sportsbook/{sport}/{league}/game/{id}`` + a ``window.__INITIAL_STATE__``
  blob), so their parsers are reused directly from :mod:`sports_data.sources`
  — never duplicated: ``bookmaker``, ``sportsbetting``, ``betanysports``,
  ``wagerweb``, ``lowvig``.
* Standalone books (``heritage``, ``mybookie``, ``betus``, ``jazzsports``,
  ``nitrobetting``, ``youwager``, ``everygame``, ``gtbets``) run a generic
  embedded-state walk + a conservative decimal-odds HTML row parser; their
  markup is JS-heavy so plain HTTP often returns no odds — that is flagged
  honestly (never silently treated as "no odds").

Contract
--------
* :func:`fetch_offshore_odds` aggregates every per-book fetcher and never
  raises — it returns ``[]`` on any failure (network, block, malformed
  payload, unsupported sport). One dead book never affects the others.
* Every record follows the canonical odds schema from
  :mod:`sports_data.odds` (``sport, event, market, book, bookmaker, home,
  away, home_odds, away_odds, draw_odds, spread, total, last_update,
  source``). Records produced here are tagged ``source="offshore"``; the
  reused Bovada/BetOnline records keep their original ``source`` tag.
* :data:`OFFSHORE_BOOKS` is the static registry (name, base url, kind,
  confidence, notes); :func:`book_status` adds the live per-book
  availability seen by the last fetch.

Free-API terms: all feeds are unofficial public pages — scrape politely,
expect layout drift and geo-blocks.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from typing import Any

# Guarded odds helpers re-exported from the registry module (the guarded
# import lives there; re-exported here so ``offshore._american_to_decimal``
# etc. keep working for external callers).
from datasets.sports_data.offshore_books import (  # noqa: F401
    _BETONLINE_FAMILY,
    _BOOK_HEALTH,
    _OFFSHORE_SPORTS,
    _SPORTS,
    OFFSHORE_BOOK_ORDER,
    OFFSHORE_BOOKS,
    _american_to_decimal,
    _event_label,
    _mark_book,
    _resolve_sports,
    _status_entry,
    available_books,
    book_status,
    book_supports,
)
from datasets.sports_data.offshore_fetchers import (  # noqa: F401
    _book_url,
    _canonical_sport,
    _fetch_book,
    fetch_betanysports,
    fetch_betus,
    fetch_bookmaker,
    fetch_everygame,
    fetch_gtbets,
    fetch_heritage,
    fetch_jazzsports,
    fetch_lowvig,
    fetch_mybookie,
    fetch_nitrobetting,
    fetch_offshore_odds,
    fetch_sportsbetting,
    fetch_wagerweb,
    fetch_youwager,
)
from datasets.sports_data.offshore_parsers import (  # noqa: F401
    _DECIMAL_ODDS_RE,
    _US_ODDS_RE,
    _parse_decimal_rows,
    _parse_embedded_state,
)
from datasets.sports_data.offshore_transport import (  # noqa: F401
    _RETRY_CONFIG,
    _TIMEOUT,
    _fetch_json_geo,
    _fetch_text_geo,
)
from datasets.sports_data.sources import _looks_blocked, _monotonic  # noqa: F401
from pry.engine.webshare_proxy import next_webshare_proxy  # noqa: F401

# ── Live availability tracking (kept here so tests can monkeypatch) ─────
# Guarded reuse of the sibling BOOKS registry (sports_data.books — owned by
# another agent in this batch). When present, book_status() annotates each
# entry with the sibling's geo/method metadata; fetch logic stays fully
# independent, so this degrades to no-op if the sibling module is missing.
try:
    import datasets.sports_data.books as _sibling_books

    _SIBLING_BOOKS: dict[str, dict[str, Any]] | None = getattr(_sibling_books, "BOOKS", None)
except ImportError:  # pragma: no cover - sibling module may not exist yet
    _SIBLING_BOOKS = None

# My slugs that don't match the sibling's book ids / display names directly.
_SIBLING_ALIASES: dict[str, str] = {"sportsbetting": "sportsbetting-ag"}


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
