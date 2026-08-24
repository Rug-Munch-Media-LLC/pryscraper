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

_TEAM_MARKETS = frozenset(
    {
        "h2h",
        "spread",
        "spreads",
        "total",
        "totals",
        "alternate_spread",
        "alternate_spreads",
        "alternate_total",
        "alternate_totals",
        "ou",
        "ml",
        "moneyline",
    }
)

# Team markets eligible for sharp-book fair-prob anchoring. Player props
# keep their own book's no-vig probability (lines/players differ per book).
_ANCHORED_MARKETS = frozenset({"h2h", "spread", "total"})

# Maximum opportunities returned / legs+combos considered — the scan stays
# bounded so a prop-heavy event can never explode the caller's memory.
_MAX_OPPORTUNITIES = 30
_MAX_POOL_LEGS = 40
_MAX_COMBOS = 600

_DEFAULT_MIN_EV = 2.0


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


def _normalize_market(value: Any) -> str:
    """Lower-case, alias-free market name ('spreads' -> 'spread')."""
    market = str(value or "").strip().lower()
    return {
        "spreads": "spread",
        "totals": "total",
        "ou": "total",
        "ml": "h2h",
        "moneyline": "h2h",
        "alternate_spreads": "alternate_spread",
        "alternate_totals": "alternate_total",
    }.get(market, market)


# ── Leg normalization (build_same_game_parlay) ─────────────────────────
def _leg_label(market: str, side: str, line: Any, player: str | None) -> str:
    """Build a compact display label for one leg."""
    line_text = ""
    if line is not None:
        value = _to_float(line)
        if value is not None:
            line_text = f" {value:g}" if value == int(value) else f" {value:.1f}"
    if player:
        return f"{player}{line_text}"
    side_lower = side.strip().lower()
    if side_lower in {"over", "under"}:
        return f"{side_lower.capitalize()}{line_text}"
    if side_lower in {"home", "away"}:
        return f"{side_lower.capitalize()}{line_text}"
    return f"{side}{line_text}"


def _normalize_leg(leg: Any, index: int) -> dict[str, Any] | None:
    """Validate/coerce one caller-supplied leg into the canonical shape."""
    if not isinstance(leg, dict):
        return None
    odds = _to_float(leg.get("odds"))
    if odds is None or odds <= 1.0:
        return None
    market = _normalize_market(leg.get("market") or "")
    if not market:
        return None
    player = _as_text(leg.get("player"))
    team = _as_text(leg.get("team"))
    line = _to_float(leg.get("line"))
    side = (
        str(leg.get("side") or "").strip()
        or str(leg.get("selection") or "").strip()
        or (player or "")
    )
    if not side:
        return None
    label = _as_text(leg.get("label")) or _leg_label(market, side, line, player)
    return {
        "index": index,
        "market": market,
        "side": side,
        "player": player,
        "team": team,
        "line": line,
        "odds": odds,
        "implied_prob": round(1.0 / odds, 6),
        "label": label,
        "book": _as_text(leg.get("book")),
    }


def _leg_entities(leg: dict[str, Any]) -> tuple[set[str], bool]:
    """Return (entity tokens, is_player_leg) for the correlation heuristic."""
    tokens: set[str] = set()
    player = leg.get("player")
    team = leg.get("team")
    market = str(leg.get("market") or "")
    side = str(leg.get("side") or "").strip().lower()
    if player:
        tokens.add(f"player:{str(player).casefold()}")
    if team:
        tokens.add(f"team:{str(team).casefold()}")
    if market in _TEAM_MARKETS:
        if side in {"home", "away"}:
            tokens.add(f"side:{side}")
        elif side in {"over", "under"}:
            tokens.add("side:over-under")
    is_player = market.startswith("player_") or bool(player)
    return tokens, is_player


def _correlated(legs: list[dict[str, Any]]) -> bool:
    """Deterministic correlation heuristic over normalized legs (see docstring)."""
    if len(legs) < 2:
        return False
    entities: list[tuple[set[str], bool]] = [_leg_entities(leg) for leg in legs]
    seen: set[str] = set()
    for tokens, _is_player in entities:
        if tokens & seen:
            return True
        seen |= tokens
    # No shared entity: flag the classic correlated team-market structure —
    # at least two team-level legs across at least two market classes.
    team_markets = {
        str(leg.get("market") or "") for leg in legs if leg.get("market") in _TEAM_MARKETS
    }
    return len(team_markets) >= 2


# ── Public API: build_same_game_parlay ─────────────────────────────────
async def build_same_game_parlay(
    event_id: str, legs: list[dict[str, Any]], book: str = "all"
) -> dict[str, Any]:
    """Price a same-game parlay from caller-supplied legs.

    Args:
        event_id: The event id (e.g. ``"nba:eid123"``). Carried through for
            context; no network call is made.
        legs: List of leg dicts (see module docstring). At least two valid
            legs are required; any invalid leg (missing/bad odds, unknown
            market) is dropped.
        book: Optional book label used when the legs do not carry one
            (``"all"`` default means "no single book").

    Returns:
        A parlay record (see module docstring) or ``{}`` when fewer than
        two valid legs remain. Never raises.
    """
    try:
        return _build_same_game_parlay(event_id, legs, book)
    except Exception:
        logger.exception("sports_parlay_build_crashed", extra={"event_id": event_id})
        return {}


def _build_same_game_parlay(event_id: str, legs: list[dict[str, Any]], book: str) -> dict[str, Any]:
    normalized: list[dict[str, Any]] = []
    for index, leg in enumerate(legs or []):
        norm = _normalize_leg(leg, index)
        if norm is not None:
            normalized.append(norm)
    if len(normalized) < 2:
        return {}
    combined = 1.0
    implied = 1.0
    for leg in normalized:
        combined *= float(leg["odds"])
        implied *= float(leg["implied_prob"])
    books = {str(leg.get("book") or "").strip().lower() for leg in normalized}
    books.discard("")
    if len(books) == 1:
        book_label = next(iter(books))
    elif book and str(book).strip().lower() not in {"", "all"}:
        book_label = str(book).strip().lower()
    elif books:
        book_label = "mixed"
    else:
        book_label = "all"
    label = " + ".join(str(leg["label"]) for leg in normalized)
    return {
        "parlay": {
            "label": label,
            "event_id": str(event_id or ""),
            "book": book_label,
            "leg_count": len(normalized),
        },
        "legs": normalized,
        "combined_odds": round(combined, 6),
        "implied_prob": round(implied, 6),
        "correlation_flag": _correlated(normalized),
        "source": "parlay_math",
    }


# ── Opportunity scan ────────────────────────────────────────────────────
def _comparison_team_names(
    comparison: dict[str, Any],
) -> tuple[str | None, str | None]:
    """Best-effort (home, away) names from an event comparison dict.

    ``get_event_odds`` does not expose team names directly, so this parses
    the conventional ``"Away @ Home"`` event label as a fallback and finally
    falls back to outcome names from the h2h market.
    """
    event = _as_text(comparison.get("event"))
    if event and "@" in event:
        away, _, home = event.partition("@")
        away_name = away.strip() or None
        home_name = home.strip() or None
        if away_name and home_name:
            return home_name, away_name
    bookmakers = comparison.get("bookmakers")
    if isinstance(bookmakers, list):
        for bk in bookmakers:
            if not isinstance(bk, dict):
                continue
            for mkt in bk.get("markets") or []:
                if not isinstance(mkt, dict):
                    continue
                if str(mkt.get("key") or "").lower() != "h2h":
                    continue
                names = [
                    str(outcome.get("name")).strip()
                    for outcome in mkt.get("outcomes") or []
                    if isinstance(outcome, dict) and outcome.get("name")
                ]
                if len(names) >= 2:
                    return names[0], names[1]
    return None, None


def _fair_probability(
    side_price: float, odds_a: float | None, odds_b: float | None
) -> float | None:
    """No-vig fair probability for the side priced at ``side_price``.

    Uses :func:`sports_data.ev.compute_no_vig` when both sides are present
    (guarded import), otherwise falls back to the raw implied probability.
    ``side_price`` must equal one of ``odds_a``/``odds_b`` so the correct
    side's probability is returned.
    """
    if odds_a is None or odds_b is None:
        return round(1.0 / side_price, 6)
    if odds_a <= 1.0 or odds_b <= 1.0:
        return round(1.0 / side_price, 6)
    if _compute_no_vig is not None:
        try:
            fair = _compute_no_vig(odds_a, odds_b)
        except Exception:  # noqa: BLE001 - helper contract is never-raise
            fair = {}
        prob_a = fair.get("home_prob")
        prob_b = fair.get("away_prob")
        if isinstance(prob_a, (int, float)) and side_price == odds_a:
            return round(float(prob_a), 6)
        if isinstance(prob_b, (int, float)) and side_price == odds_b:
            return round(float(prob_b), 6)
    return round(1.0 / side_price, 6)


def _market_legs_from_outcomes(
    market_key: str,
    outcomes: list[dict[str, Any]],
    home_name: str | None,
    away_name: str | None,
    book: str,
) -> list[dict[str, Any]]:
    """Build normalized legs from one bookmaker's market outcomes."""
    key = str(market_key or "").lower()
    legs: list[dict[str, Any]] = []
    # Only entries with a non-None price are appended (guarded at build time),
    # so the price slot is a plain float.
    priced: list[tuple[str, float, float | None]] = []

    if key == "h2h":
        for outcome in outcomes:
            name = _as_text(outcome.get("name"))
            price = _to_float(outcome.get("price"))
            if not name or price is None:
                continue
            priced.append((name, price, None))
    elif key in {"spreads", "spread"}:
        for outcome in outcomes:
            name = _as_text(outcome.get("name"))
            price = _to_float(outcome.get("price"))
            point = _to_float(outcome.get("point"))
            if not name or price is None:
                continue
            priced.append((name, price, point))
    elif key in {"totals", "total"}:
        for outcome in outcomes:
            name = str(outcome.get("name") or "").strip().lower()
            price = _to_float(outcome.get("price"))
            point = _to_float(outcome.get("point"))
            if name not in {"over", "under", "o", "u"} or price is None:
                continue
            side = "over" if name in {"over", "o"} else "under"
            priced.append((side, price, point))
    else:
        return legs

    if key == "h2h":
        side_odds = [odds for _name, odds, _pt in priced[:2] if odds is not None]
        for name, price, _point in priced:
            fair = _fair_probability(
                float(price),
                side_odds[0] if side_odds else None,
                side_odds[1] if len(side_odds) > 1 else None,
            )
            legs.append(
                {
                    "market": "h2h",
                    "side": name,
                    "team": name,
                    "line": None,
                    "odds": float(price),
                    "fair_prob": fair,
                    "implied_prob": round(1.0 / float(price), 6),
                    "label": name,
                    "book": book,
                }
            )
    elif key in {"spreads", "spread"}:
        side_odds = [odds for _name, odds, _pt in priced[:2] if odds is not None]
        for name, price, point in priced:
            fair = _fair_probability(
                float(price),
                side_odds[0] if side_odds else None,
                side_odds[1] if len(side_odds) > 1 else None,
            )
            side = name
            if home_name and away_name:
                if name.casefold() == home_name.casefold():
                    side = "home"
                elif name.casefold() == away_name.casefold():
                    side = "away"
            legs.append(
                {
                    "market": "spread",
                    "side": side,
                    "team": name,
                    "line": point,
                    "odds": float(price),
                    "fair_prob": fair,
                    "implied_prob": round(1.0 / float(price), 6),
                    "label": f"{name} {point:+.1f}" if point is not None else name,
                    "book": book,
                }
            )
    elif key in {"totals", "total"}:
        over_odds = next((o for s, o, _p in priced if s == "over"), None)
        under_odds = next((o for s, o, _p in priced if s == "under"), None)
        total = next((p for _s, _o, p in priced if p is not None), None)
        for side, price, _point in priced:
            fair = _fair_probability(float(price), over_odds, under_odds)
            side_name = "Over" if side == "over" else "Under"
            legs.append(
                {
                    "market": "total",
                    "side": side,
                    "team": None,
                    "line": total,
                    "odds": float(price),
                    "fair_prob": fair,
                    "implied_prob": round(1.0 / float(price), 6),
                    "label": f"{side_name} {total}" if total is not None else side_name,
                    "book": book,
                }
            )
    return legs


def _prop_legs_from_records(records: list[dict[str, Any]], book: str) -> list[dict[str, Any]]:
    """Build over/under legs from game-prop records for one book."""
    legs: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        if str(record.get("book") or "").casefold() != book.casefold():
            continue
        player = _as_text(record.get("player"))
        if not player:
            continue
        market = str(record.get("market") or "").strip().lower()
        line = _to_float(record.get("line"))
        over_odds = _to_float(record.get("over_odds"))
        under_odds = _to_float(record.get("under_odds"))
        if over_odds is not None:
            fair = _fair_probability(over_odds, over_odds, under_odds)
            legs.append(
                {
                    "market": market,
                    "side": "over",
                    "player": player,
                    "team": _as_text(record.get("team")),
                    "line": line,
                    "odds": over_odds,
                    "fair_prob": fair,
                    "implied_prob": round(1.0 / over_odds, 6),
                    "label": f"{player} Over {line}" if line is not None else f"{player} Over",
                    "book": book,
                }
            )
        if under_odds is not None:
            fair = _fair_probability(under_odds, over_odds, under_odds)
            legs.append(
                {
                    "market": market,
                    "side": "under",
                    "player": player,
                    "team": _as_text(record.get("team")),
                    "line": line,
                    "odds": under_odds,
                    "fair_prob": fair,
                    "implied_prob": round(1.0 / under_odds, 6),
                    "label": f"{player} Under {line}" if line is not None else f"{player} Under",
                    "book": book,
                }
            )
    return legs


def _leg_identity(leg: dict[str, Any]) -> tuple[str, str, str]:
    """Identity used to dedupe the best price per leg across books."""
    market = str(leg.get("market") or "")
    side = str(leg.get("side") or "").strip().lower()
    player = str(leg.get("player") or "").casefold()
    return (market, side, player)


def _market_anchor_fair(
    legs_by_market: dict[str, list[dict[str, Any]]], market: str
) -> dict[str, float]:
    """Fair probabilities for a team market from its sharpest (lowest-margin) book."""
    legs = legs_by_market.get(market, [])
    by_book: dict[str, list[dict[str, Any]]] = {}
    for leg in legs:
        by_book.setdefault(str(leg.get("book") or "unknown"), []).append(leg)
    best_margin: float | None = None
    best_fair: dict[str, float] = {}
    for _book, book_legs in by_book.items():
        sides: dict[str, float] = {}
        for leg in book_legs:
            side = str(leg.get("side") or "").strip().lower()
            if side and side not in sides:
                sides[side] = float(leg["odds"])
        if len(sides) < 2 or _compute_no_vig is None:
            continue
        side_keys = list(sides)
        try:
            fair = _compute_no_vig(sides[side_keys[0]], sides[side_keys[1]])
        except Exception:  # noqa: BLE001 - helper contract is never-raise
            fair = {}
        margin = fair.get("margin")
        prob_a = fair.get("home_prob")
        prob_b = fair.get("away_prob")
        if not isinstance(margin, (int, float)) or not isinstance(prob_a, (int, float)):
            continue
        if not isinstance(prob_b, (int, float)):
            continue
        if best_margin is None or float(margin) < best_margin:
            best_margin = float(margin)
            best_fair = {
                side_keys[0]: round(float(prob_a), 6),
                side_keys[1]: round(float(prob_b), 6),
            }
    return best_fair


def _best_leg_pool(legs_by_market: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Collapse per-book legs to the best price per identity, anchored fair probs.

    Team markets get their fair probabilities from the sharpest book; player
    props keep their own book's no-vig probability (lines differ per book).
    """
    anchors: dict[str, dict[str, float]] = {}
    for market in _ANCHORED_MARKETS:
        anchors[market] = _market_anchor_fair(legs_by_market, market)
    best: dict[tuple[str, str, str], dict[str, Any]] = {}
    for market, legs in legs_by_market.items():
        for leg in legs:
            ident = _leg_identity(leg)
            current = best.get(ident)
            if current is not None and float(leg["odds"]) <= float(current["odds"]):
                continue
            out = dict(leg)
            fair = anchors.get(market, {}).get(str(leg.get("side") or "").lower())
            if fair is not None:
                out["fair_prob"] = fair
            best[ident] = out
    return list(best.values())


def _different_class(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """True when two legs belong to different market classes."""

    def _class(leg: dict[str, Any]) -> str:
        market = str(leg.get("market") or "")
        if market.startswith("player_"):
            return "prop"
        if market in {"spread", "alternate_spread"}:
            return "spread"
        if market in {"total", "alternate_total"}:
            return "total"
        return "h2h"

    return _class(a) != _class(b)


def _combo_book(a: dict[str, Any], b: dict[str, Any]) -> str:
    """Book label for a 2-leg combo ('mixed' when legs come from different books)."""
    book_a = str(a.get("book") or "").strip().lower()
    book_b = str(b.get("book") or "").strip().lower()
    if book_a and book_a == book_b:
        return book_a
    if book_a and book_b:
        return "mixed"
    return book_a or book_b or "unknown"


def _scan_pool(
    pool: list[dict[str, Any]],
    *,
    event_id: str,
    event: str,
    sport: str,
    threshold: float,
) -> list[dict[str, Any]]:
    """Enumerate bounded 2-leg cross-class combos over the best-leg pool."""
    capped = pool[:_MAX_POOL_LEGS]
    if len(capped) < 2:
        return []
    edges: list[dict[str, Any]] = []
    counted = 0
    for i in range(len(capped)):
        for j in range(i + 1, len(capped)):
            counted += 1
            if counted > _MAX_COMBOS:
                return edges
            a, b = capped[i], capped[j]
            if not _different_class(a, b):
                continue
            if a.get("fair_prob") is None or b.get("fair_prob") is None:
                continue
            combined_odds = float(a["odds"]) * float(b["odds"])
            implied = float(a["implied_prob"]) * float(b["implied_prob"])
            fair = float(a["fair_prob"]) * float(b["fair_prob"])
            ev_pct = (fair * combined_odds - 1.0) * 100.0
            if ev_pct < threshold:
                continue
            legs_out = [
                {
                    key: leg.get(key)
                    for key in ("market", "side", "player", "team", "line", "odds", "label")
                }
                for leg in (a, b)
            ]
            edges.append(
                {
                    "event_id": event_id,
                    "event": event,
                    "sport": sport,
                    "book": _combo_book(a, b),
                    "legs": legs_out,
                    "combined_odds": round(combined_odds, 4),
                    "implied_prob": round(implied, 6),
                    "fair_prob": round(fair, 6),
                    "ev_pct": round(ev_pct, 2),
                    "correlation_flag": _correlated([a, b]),
                    "source": "sgp_scan",
                }
            )
    edges.sort(key=lambda item: float(item.get("ev_pct") or 0.0), reverse=True)
    return edges


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
