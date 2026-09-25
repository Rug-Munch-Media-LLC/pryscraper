"""Deterministic best-price selection for parlay legs.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from typing import Any

from datasets.sports_data.parlay_legs.fair import _ANCHORED_MARKETS, _market_anchor_fair

_MAX_INPUT_MARKETS = 1_000
_MAX_INPUT_LEGS = 10_000


def _leg_identity(leg: dict[str, Any]) -> tuple[str, str, str]:
    """Identity used to dedupe the best price per leg across books."""
    market = str(leg.get("market") or "")
    side = str(leg.get("side") or "").strip().lower()
    player = str(leg.get("player") or "").casefold()
    return (market, side, player)


def _best_leg_pool(legs_by_market: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Collapse per-book legs to the best price per identity, anchored fair probs.

    Team markets get their fair probabilities from the sharpest book; player
    props keep their own book's no-vig probability (lines differ per book).
    """
    if len(legs_by_market) > _MAX_INPUT_MARKETS:
        raise ValueError("legs_by_market exceeds market limit")
    if sum(len(legs) for legs in legs_by_market.values()) > _MAX_INPUT_LEGS:
        raise ValueError("legs_by_market exceeds leg limit")
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
