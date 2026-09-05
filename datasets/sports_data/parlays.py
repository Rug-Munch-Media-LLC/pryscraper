"""Same-game parlays (SGPs) — parlay math + correlated-prop opportunity scan.

Sportsbooks now offer single-event parlays (SGPs) that combine a moneyline,
spread, total and player props from the *same* game. This module provides
the two pieces a betting bot needs to play them:

* :func:`build_same_game_parlay` — pure parlay math for an arbitrary set of
  legs: combined (parlay) decimal odds, the implied probability under the
  independence assumption (product of per-leg implied probabilities) and a
  deterministic :dfn:`correlation_flag` heuristic that marks combos whose
  legs share an entity (player or team) or mix classic correlated team
  markets (spread + total, moneyline + total, ...). No network involved —
  the legs the caller passes are the legs that get priced.
* :func:`find_parlay_opportunities` — scans one event's live bookmaker
  markets (via :mod:`sports_data.odds` comparison + :mod:`sports_data.props`
  game props, both imported with a guarded import so this module is safe
  when they are missing) and returns 2-leg same-game combos whose
  *independent* no-vig probability clears the combined price. It reuses the
  sharp-book anchoring from :mod:`sports_data.ev` (fair probabilities come
  from the lowest-margin book per market) and the best-side selection from
  :mod:`sports_data.arbitrage` (the best price per leg wins). The EV is
  computed under the independence assumption — correlated flags are
  reported explicitly so callers can decide whether the book's SGP
  adjustment already prices the correlation.

Contract
--------
* :func:`build_same_game_parlay` — async, never raises, returns a ``dict``
  (``{}`` on unusable input). Pure math on the supplied legs.
* :func:`find_parlay_opportunities` — async, never raises, returns a
  ``list`` (``[]`` on failure / no data / no edges).

Result shapes
-------------
``build_same_game_parlay`` returns:

    {
        "parlay": {
            "label": "Lakers -5.5 + Over 224.5 + LeBron James Over 25.5 pts",
            "event_id": "nba:eid123",
            "book": "draftkings",
            "leg_count": 3,
        },
        "legs": [{"market": "spread", "side": "home", "team": "Lakers",
                   "line": -5.5, "odds": 1.91, "implied_prob": 0.5236,
                   "label": "Lakers -5.5"}, ...],
        "combined_odds": 5.32,
        "implied_prob": 0.188,          # product of per-leg implied probs
        "correlation_flag": True,
        "source": "parlay_math",
    }

``find_parlay_opportunities`` returns a list of:

    {
        "event_id": "nba:eid123",
        "event": "Celtics @ Lakers",
        "sport": "basketball_nba",
        "book": "draftkings",           # same book for both legs, else "mixed"
        "legs": [<leg>, <leg>],
        "combined_odds": 4.18,
        "implied_prob": 0.2392,          # product of per-leg implied probs
        "fair_prob": 0.25,               # product of no-vig fair probs
        "ev_pct": 4.5,                   # (fair_prob * combined_odds - 1) * 100
        "correlation_flag": True,
        "source": "sgp_scan",
    }

Leg dicts
---------
Each leg passed to :func:`build_same_game_parlay` is a dict with:

* ``market`` (str): ``"h2h"``, ``"spread"``, ``"total"``,
  ``"alternate_spread"``, ``"alternate_total"``, or any ``player_*`` key
  (e.g. ``"player_points"``). Case-insensitive.
* ``side`` (str): ``"home"``/``"away"``/``"over"``/``"under"`` for team
  markets, or the selection name (e.g. ``"Lakers"``, ``"Over"``).
* ``odds`` (float, required): decimal odds for the leg.
* ``line`` (float, optional): spread/total/prop line.
* ``player`` (str, optional): player name for player props.
* ``team`` (str, optional): team name — used by the correlation heuristic
  when a player prop is tied to a team-level leg.
* ``label`` (str, optional): display label; auto-built when missing.

Correlation heuristic
---------------------
``correlation_flag`` is ``True`` when any of these hold (checked in order):

1. Two legs reference the same player (a player + a player/team combo).
2. Two legs reference the same team (explicit ``team`` or inferred side).
3. No entity info is present, but the legs contain at least two team-level
   legs spanning at least two different market classes (spread + total,
   h2h + total, h2h + spread, ...) — the classic correlated SGP structure.

Two independent player props on different players/teams are *not* flagged.

Free-API terms: https://the-odds-api.com. Backoff: 1 retry, exponential
(0.1s -> 0.4s) — only the opportunity scan touches the network.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Guarded imports: the sibling modules are owned by other agents / may be
# missing when this module is first imported (parallel build safety).
try:
    from datasets.sports_data.ev import compute_no_vig as _compute_no_vig
except ImportError:  # pragma: no cover - parallel build guard
    _compute_no_vig = None  # type: ignore[assignment]

try:
    from datasets.sports_data.odds import get_event_odds as _get_event_odds
except ImportError:  # pragma: no cover - parallel build guard
    _get_event_odds = None  # type: ignore[assignment]

try:
    from datasets.sports_data.props import get_game_props as _get_game_props
except ImportError:  # pragma: no cover - parallel build guard
    _get_game_props = None  # type: ignore[assignment]

# Split modules (file-size limits): pure math lives in parlay_math, leg
# extraction + scan helpers live in parlay_legs. This module is the public
# facade — re-exports below keep the historical ``parlays.*`` surface.
from datasets.sports_data.parlay_legs import (  # noqa: E402,F401
    _ANCHORED_MARKETS,
    _MAX_COMBOS,
    _MAX_POOL_LEGS,
    _best_leg_pool,
    _combo_book,
    _comparison_team_names,
    _different_class,
    _fair_probability,
    _leg_identity,
    _market_anchor_fair,
    _market_legs_from_outcomes,
    _prop_legs_from_records,
    _scan_pool,
)
from datasets.sports_data.parlay_math import (  # noqa: E402,F401
    _TEAM_MARKETS,
    _as_text,
    _build_same_game_parlay,
    _correlated,
    _leg_entities,
    _leg_label,
    _normalize_leg,
    _normalize_market,
    _to_float,
    build_same_game_parlay,
)

_MAX_OPPORTUNITIES = 30

_DEFAULT_MIN_EV = 2.0


async def find_parlay_opportunities(
    event_id: str, min_ev_pct: float = _DEFAULT_MIN_EV
) -> list[dict[str, Any]]:
    """Scan one event for +EV same-game parlay combos.

    Loads the event's bookmaker markets (``sports_data.odds.get_event_odds``)
    and player props (``sports_data.props.get_game_props``, best-effort),
    anchors fair probabilities on the sharpest book per market
    (:mod:`sports_data.ev` math) and picks the best price per leg
    (:mod:`sports_data.arbitrage`-style), then evaluates 2-leg cross-market
    combos. Combos clearing ``min_ev_pct`` are returned best-EV first.

    Args:
        event_id: The event id (optionally ``sport:event_id`` prefixed).
        min_ev_pct: Minimum expected value (percent) to keep a combo.

    Returns:
        List of opportunity records (see module docstring). ``[]`` on
        failure, missing sources, or no clearing combos. Never raises.
    """
    try:
        threshold = max(0.0, float(min_ev_pct))
    except (TypeError, ValueError):
        threshold = _DEFAULT_MIN_EV
    try:
        return await _find_parlay_opportunities(event_id, threshold)
    except Exception:
        logger.exception(
            "sports_parlay_scan_crashed",
            extra={"event_id": event_id, "min_ev_pct": min_ev_pct},
        )
        return []


async def _find_parlay_opportunities(event_id: str, threshold: float) -> list[dict[str, Any]]:
    if not event_id or not str(event_id).strip():
        return []
    if _get_event_odds is None:
        return []
    comparison: dict[str, Any] = {}
    try:
        comparison = await _get_event_odds(event_id, market="h2h,spreads,totals")
    except Exception:  # noqa: BLE001 - source contract is never-raise
        logger.warning("sports_parlay_event_odds_failed", extra={"event_id": event_id})
    if not isinstance(comparison, dict) or not comparison.get("bookmakers"):
        return []
    sport = str(comparison.get("sport") or "")
    event = str(comparison.get("event") or "")
    home_name, away_name = _comparison_team_names(comparison)

    props_records: list[dict[str, Any]] = []
    if _get_game_props is not None:
        try:
            props_records = await _get_game_props(event_id)
        except Exception:  # noqa: BLE001 - source contract is never-raise
            logger.warning("sports_parlay_game_props_failed", extra={"event_id": event_id})
    if not isinstance(props_records, list):
        props_records = []

    legs_by_market: dict[str, list[dict[str, Any]]] = {}
    for bk in comparison.get("bookmakers") or []:
        if not isinstance(bk, dict):
            continue
        book = str(bk.get("book") or bk.get("title") or bk.get("key") or "unknown").strip().lower()
        if not book or book == "unknown":
            book = str(bk.get("title") or "unknown").strip().lower()
        for mkt in bk.get("markets") or []:
            if not isinstance(mkt, dict):
                continue
            outcomes = mkt.get("outcomes")
            if not isinstance(outcomes, list):
                continue
            market = str(mkt.get("key") or "").strip().lower()
            if market not in {"h2h", "spreads", "spread", "totals", "total"}:
                continue
            legs = _market_legs_from_outcomes(
                market,
                [o for o in outcomes if isinstance(o, dict)],
                home_name,
                away_name,
                book,
            )
            legs_by_market.setdefault(
                "h2h" if market == "h2h" else ("spread" if "spread" in market else "total"), []
            ).extend(legs)
        legs_by_market.setdefault("props", []).extend(_prop_legs_from_records(props_records, book))

    pool = _best_leg_pool(legs_by_market)
    return _scan_pool(
        pool,
        event_id=str(event_id),
        event=event,
        sport=sport,
        threshold=threshold,
    )[:_MAX_OPPORTUNITIES]
