"""MCP schema and guarded dispatch for pure-math exotic-bet pricing."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

PRY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_derivatives",
        "description": (
            "Price exotic bet derivatives — teasers, pleasers, if-bets, reverse "
            "bets, and round robins. Calculate adjusted lines, combined odds, "
            "payout scenarios, max win/loss, and breakeven points. "
            "Use to compare exotic bet structures before placing, e.g. 'price a "
            "6-point teaser on these two spreads' or 'what does a 3-team round "
            "robin risk and pay?'. Pure math on the legs you supply — no live "
            "odds are fetched."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "bet_type": {
                    "type": "string",
                    "enum": ["teaser", "pleaser", "if_bet", "reverse", "round_robin"],
                    "description": (
                        "Exotic bet type: teaser (points in your favor), pleaser "
                        "(points against you), if_bet (conditional chain), reverse "
                        "(two if-bets both directions), round_robin (all N-leg "
                        "parlay combinations)"
                    ),
                },
                "legs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "selection": {"type": "string"},
                            "odds": {"type": "number"},
                            "type": {"type": "string"},
                        },
                        "required": ["selection", "odds"],
                    },
                    "description": (
                        "Bet legs: each with selection label, odds (American like "
                        "-110/+150 or decimal like 1.91 — auto-detected) and type "
                        "(spread/total are teaser-adjustable; h2h is not)"
                    ),
                },
                "adjustment": {
                    "type": "integer",
                    "default": 6,
                    "minimum": 0,
                    "maximum": 20,
                    "description": ("Points of adjustment per leg for teaser/pleaser (default: 6)"),
                },
                "parlay_size": {
                    "type": "integer",
                    "default": 2,
                    "minimum": 2,
                    "maximum": 10,
                    "description": ("Legs per parlay in a round robin (default: 2)"),
                },
                "max_risk": {
                    "type": "number",
                    "default": 100,
                    "minimum": 0,
                    "description": (
                        "Stake/budget in dollars: per leg for if-bets, per chain "
                        "for reverses, total budget split across round-robin "
                        "parlays (default: 100)"
                    ),
                },
            },
            "required": ["bet_type", "legs"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {"type": "object"},
                "bet_type": {"type": "string"},
                "error": {"type": "string"},
            },
            "required": ["success"],
        },
    },
]

# Guarded candidate registry for pure-math pricing functions.
_DERIVATIVES_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_derivatives": (
        (
            "derivatives",
            (
                "price_teaser",
                "price_pleaser",
                "price_if_bet",
                "price_reverse_bet",
                "price_round_robin",
            ),
        ),
    ),
}

_BET_TYPE_FNS: dict[str, tuple[str, ...]] = {
    "teaser": ("price_teaser",),
    "pleaser": ("price_teaser",),  # direction='pleaser'
    "if_bet": ("price_if_bet",),
    "reverse": ("price_reverse_bet",),
    "round_robin": ("price_round_robin",),
}


_MAX_LEGS_BY_BET_TYPE = {"teaser": 20, "pleaser": 20, "if_bet": 12, "reverse": 2, "round_robin": 20}
_MAX_ROUND_ROBIN_COMBINATIONS = 1_000


def _finite_float(value: Any, default: float) -> float:
    try:
        number = float(default if value is None else value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError from exc
    if isinstance(value, bool) or not math.isfinite(number):
        raise ValueError
    return number


def _validated_options(
    bet_type: str, legs: list[Any], arguments: dict[str, Any]
) -> dict[str, float | int]:
    if len(legs) > _MAX_LEGS_BY_BET_TYPE[bet_type]:
        raise ValueError
    for leg in legs:
        if isinstance(leg, dict) and "odds" in leg:
            _finite_float(leg["odds"], 0)
    if bet_type in {"teaser", "pleaser"}:
        adjustment = _finite_float(arguments.get("adjustment"), 6)
        if not adjustment.is_integer() or not 0 <= adjustment <= 20:
            raise ValueError
        return {"adjustment": int(adjustment)}
    max_risk = _finite_float(arguments.get("max_risk"), 100)
    if max_risk < 0:
        raise ValueError
    if bet_type != "round_robin":
        return {"max_risk": max_risk}
    size = _finite_float(arguments.get("parlay_size"), 2)
    if not size.is_integer() or not 2 <= size <= 10:
        raise ValueError
    size = int(size)
    if math.comb(len(legs), size) > _MAX_ROUND_ROBIN_COMBINATIONS:
        raise ValueError
    return {"max_risk": max_risk, "parlay_size": size}


def call_sports_derivatives_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    """Dispatch ``pry_derivatives`` with the established envelope; never raises."""
    bet_type = str(arguments.get("bet_type") or "").strip().lower()
    legs = arguments.get("legs")
    if bet_type not in _BET_TYPE_FNS:
        return {
            "success": False,
            "error": f"Unknown bet_type {bet_type!r}; expected one of {sorted(_BET_TYPE_FNS)}",
        }
    if not isinstance(legs, list) or len(legs) < 2:
        return {"success": False, "error": "At least two legs are required"}
    try:
        options = _validated_options(bet_type, legs, arguments)
    except ValueError:
        return {"success": False, "error": "derivatives pricing failed"}
    try:
        from datasets.sports_data import derivatives
    except ImportError:
        logger.exception("sports_derivatives_module_unavailable")
        return {"success": False, "error": "derivatives module unavailable"}
    try:
        if bet_type in {"teaser", "pleaser"}:
            result = derivatives.price_teaser(
                legs, adjustment=int(options["adjustment"]), direction=bet_type
            )
        elif bet_type == "if_bet":
            result = derivatives.price_if_bet(legs, max_risk=float(options["max_risk"]))
        elif bet_type == "reverse":
            result = derivatives.price_reverse_bet(legs, max_risk=float(options["max_risk"]))
        elif bet_type == "round_robin":
            result = derivatives.price_round_robin(
                legs, parlay_size=int(options["parlay_size"]), max_risk=float(options["max_risk"])
            )
        else:  # pragma: no cover - guarded by _BET_TYPE_FNS
            return {"success": False, "error": "derivatives pricing failed"}
    except Exception:
        logger.exception("sports_derivatives_call_crashed", extra={"bet_type": bet_type})
        return {"success": False, "error": "derivatives pricing failed"}
    if not result:
        return {"success": False, "error": "Not enough valid legs to price this bet"}
    return {"success": True, "data": result, "bet_type": bet_type}
