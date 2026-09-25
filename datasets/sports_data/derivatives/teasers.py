"""Teaser and pleaser pricing."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import contextlib
import logging
from typing import Any

from .legs import _normalize_legs
from .odds_math import decimal_to_american

logger = logging.getLogger(__name__)

_PROB_PER_POINT = 0.025  # implied-probability shift per adjustment point


def _shift_prob(prob: float, points: float, toward_bettor: bool) -> float:
    """Shift an implied probability by ``points`` (2.5%/point heuristic)."""
    delta = _PROB_PER_POINT * points
    shifted = prob + delta if toward_bettor else prob - delta
    return min(0.99, max(0.01, shifted))


def _adjusted_leg(leg: dict[str, Any], adjustment: int, toward_bettor: bool) -> dict[str, Any]:
    """Return the leg with its line/odds adjusted for a teaser or pleaser."""
    out = dict(leg)
    if not leg["adjustable"] or adjustment <= 0:
        out["adjusted_odds"] = leg["odds"]
        out["adjusted_decimal"] = leg["decimal_odds"]
        out["adjusted_prob"] = leg["implied_prob"]
        return out
    sign = -1 if toward_bettor else 1  # teaser moves line in bettor's favor
    base_line = leg.get("line")
    if base_line is not None:
        with contextlib.suppress(TypeError, ValueError):
            out["adjusted_line"] = round(float(base_line) + sign * adjustment, 2)
    prob = _shift_prob(leg["implied_prob"], adjustment, toward_bettor)
    decimal = round(1.0 / prob, 6)
    out["adjusted_prob"] = round(prob, 6)
    out["adjusted_decimal"] = decimal
    out["adjusted_odds"] = decimal_to_american(decimal)
    return out


def price_teaser(
    legs: list[dict[str, Any]], adjustment: int = 6, direction: str = "teaser"
) -> dict[str, Any]:
    """Price a teaser (points in your favor) or pleaser (points against you).

    Args:
        legs: Leg dicts with ``selection``, ``odds`` and ``type`` (spread /
            total legs are adjustable; h2h legs price at their original odds).
        adjustment: Points of adjustment per leg (default 6).
        direction: ``"teaser"`` (favorable) or ``"pleaser"`` (against you).

    Returns:
        Dict with ``adjusted_lines``, ``combined_odds`` (decimal + American),
        ``implied_prob``, ``payout`` on a 100 stake, and ``breakeven`` — or
        ``{}`` when fewer than two valid legs remain. Never raises.
    """
    try:
        return _price_teaser(legs, adjustment, direction)
    except Exception:
        logger.exception("sports_teaser_price_crashed")
        return {}


def _price_teaser(legs: list[dict[str, Any]], adjustment: int, direction: str) -> dict[str, Any]:
    normalized = _normalize_legs(legs)
    if len(normalized) < 2:
        return {}
    toward = str(direction or "teaser").strip().lower() != "pleaser"
    adjusted = [_adjusted_leg(leg, max(0, int(adjustment or 0)), toward) for leg in normalized]
    combined = 1.0
    implied = 1.0
    for leg in adjusted:
        combined *= float(leg["adjusted_decimal"])
        implied *= float(leg["adjusted_prob"])
    combined = round(combined, 6)
    stake = 100.0
    return {
        "direction": "pleaser" if not toward else "teaser",
        "adjustment": int(adjustment or 0),
        "adjusted_lines": adjusted,
        "combined_odds": {
            "decimal": combined,
            "american": decimal_to_american(combined),
        },
        "implied_prob": round(implied, 6),
        "payout": {
            "stake": stake,
            "profit": round(stake * (combined - 1.0), 2),
            "total_return": round(stake * combined, 2),
        },
        "breakeven": round(1.0 / combined, 6),
        "source": "sports_derivatives",
    }
