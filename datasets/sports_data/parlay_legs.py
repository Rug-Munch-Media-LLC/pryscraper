"""Same-game parlay leg extraction from live bookmaker markets.

Source-extraction half of :mod:`sports_data.parlays` (split for file-size
limits): turns one event's bookmaker comparison (``sports_data.odds``) and
game-prop records (``sports_data.props``) into normalized candidate legs with
no-vig fair probabilities anchored on :mod:`sports_data.ev` math.

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

from datasets.sports_data.parlay_math import _as_text, _correlated, _to_float

# Team markets eligible for sharp-book fair-prob anchoring. Player props
# keep their own book's no-vig probability (lines/players differ per book).
_ANCHORED_MARKETS = frozenset({"h2h", "spread", "total"})

# Maximum pool legs / combos considered — the scan stays bounded so a
# prop-heavy event can never explode the caller's memory.
_MAX_POOL_LEGS = 40
_MAX_COMBOS = 600


def _facade() -> Any:
    """Late-bound facade module (keeps guarded imports monkeypatchable)."""
    import datasets.sports_data.parlays as m

    return m


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
    (guarded import on the facade), otherwise falls back to the raw implied
    probability. ``side_price`` must equal one of ``odds_a``/``odds_b`` so
    the correct side's probability is returned.
    """
    if odds_a is None or odds_b is None:
        return round(1.0 / side_price, 6)
    if odds_a <= 1.0 or odds_b <= 1.0:
        return round(1.0 / side_price, 6)
    compute_no_vig = _facade()._compute_no_vig
    if compute_no_vig is not None:
        try:
            fair = compute_no_vig(odds_a, odds_b)
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
        if len(sides) < 2 or _facade()._compute_no_vig is None:
            continue
        side_keys = list(sides)
        try:
            fair = _facade()._compute_no_vig(sides[side_keys[0]], sides[side_keys[1]])
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
