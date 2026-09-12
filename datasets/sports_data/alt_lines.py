"""Alternative (alternate) spread/total lines — The Odds API + ESPN fallback.

Alternate lines let a bettor move a team's spread or the game total away
from the posted number (e.g. "Lakers -3.5" instead of the market -5.5, or
"Over 230.5" instead of 224.5) at adjusted odds. Books publish these as
``alternate_spreads`` / ``alternate_totals`` markets.

Two free sources are aggregated:

* **The Odds API** (``api.the-odds-api.com``) — the real alternate markets.
  Requires a free API key via the ``PRY_ODDS_API_KEY`` env var; the per-event
  odds endpoint is called with ``markets=alternate_spreads,alternate_totals``.
  Every published alternate line carries bookmaker odds.
* **ESPN public scoreboards** (``site.api.espn.com``) — no key, no quota.
  ESPN does not publish alternate markets, so when no key is configured (or
  the Odds API call yields nothing) the module synthesizes a *modeled*
  ladder around the base spread/total ESPN publishes: lines at ~1, 2, 3.5,
  7 and 10.5 points from the base, with odds derived from a simple
  probability model plus a standard bookmaker margin. Estimates are labelled
  ``book="ESPN Estimate"``, ``source="espn_estimate"`` so callers can always
  tell real book lines from projections.

Contract
--------
* :func:`get_alt_lines` — async, never raises, returns a ``list`` (``[]``
  on failure). One record per (event, market, line, book).

Result shapes
-------------
``get_alt_lines`` returns a list of:

    {
        "event": "Celtics @ Lakers",
        "event_id": "nba:eid123",
        "sport": "nba",
        "market": "spread",
        "line": -3.5,          # home-team perspective for spreads; total for totals
        "home_odds": 1.83,
        "away_odds": 2.02,
        "book": "draftkings",
        "source": "the_odds_api",
    }

For ``market="total"`` records, ``home_odds`` is the Over price and
``away_odds`` the Under price (mirrors :mod:`sports_data.odds`).

The ``market`` parameter accepts ``"spread"``, ``"total"``, comma/pipe
separated combos, or ``"spread|total"`` / ``"all"`` (default) for both.

Backoff: 1 retry, exponential (0.1s -> 0.4s). Free-API terms:
https://the-odds-api.com.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

# Test seam re-export (tests monkeypatch alt_lines._RETRY_CONFIG to disable
# retry backoff; the split moved the constant to alt_lines_common).
from datasets.sports_data.alt_lines_common import _RETRY_CONFIG  # noqa: F401
from datasets.sports_data.alt_lines_fetchers import get_alt_lines

__all__ = ["get_alt_lines"]
