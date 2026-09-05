"""Same-game parlay math — leg normalization + correlation heuristic.

Pure-math half of :mod:`sports_data.parlays` (split for file-size limits):
normalizes caller-supplied legs, prices the parlay (combined decimal odds,
implied probability under independence) and applies the deterministic
:dfn:`correlation_flag` heuristic. No network involved — the legs the caller
passes are the legs that get priced.

Correlation heuristic
---------------------
``correlation_flag`` is ``True`` when any of these hold (checked in order):

1. Two legs reference the same player (a player + a player/team combo).
2. Two legs reference the same team (explicit ``team`` or inferred side).
3. No entity info is present, but the legs contain at least two team-level
   legs spanning at least two different market classes (spread + total,
   h2h + total, h2h + spread, ...) — the classic correlated SGP structure.

Two independent player props on different players/teams are *not* flagged.

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
        legs: List of leg dicts (see :mod:`sports_data.parlays`). At least
            two valid legs are required; any invalid leg (missing/bad odds,
            unknown market) is dropped.
        book: Optional book label used when the legs do not carry one
            (``"all"`` default means "no single book").

    Returns:
        A parlay record (see :mod:`sports_data.parlays`) or ``{}`` when
        fewer than two valid legs remain. Never raises.
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
