"""Pry - MCP tool definitions: exotic bet derivatives (teasers, reverses, RR).

Holds the ``pry_derivatives`` tool schema (``PRY_TOOLS``) and the guarded
candidate registry (``_SPORTS_DERIVATIVES_TOOL_FNS``) for the pure-math
exotic-bet pricing module (``sports_data.derivatives``). No network is
involved — the legs the caller passes are the legs that get priced.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
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

# ── Sports derivatives candidate registry (guarded) ───────────────────
# Maps the single tool to the pure-math pricing functions in
# sports_data.derivatives, tried in order per bet_type.
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


def call_sports_derivatives_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    """Dispatch ``pry_derivatives`` to the pure-math derivatives module.

    Returns an MCP-style result envelope (``success`` + ``data``/``error``).
    Never raises.
    """
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
        from datasets.sports_data import derivatives
    except ImportError:
        logger.exception("sports_derivatives_module_unavailable")
        return {"success": False, "error": "derivatives module unavailable"}
    try:
        if bet_type in {"teaser", "pleaser"}:
            result = derivatives.price_teaser(
                legs,
                adjustment=int(arguments.get("adjustment") or 6),
                direction=bet_type,
            )
        elif bet_type == "if_bet":
            result = derivatives.price_if_bet(
                legs, max_risk=float(arguments.get("max_risk") or 100)
            )
        elif bet_type == "reverse":
            result = derivatives.price_reverse_bet(
                legs, max_risk=float(arguments.get("max_risk") or 100)
            )
        else:
            result = derivatives.price_round_robin(
                legs,
                parlay_size=int(arguments.get("parlay_size") or 2),
                max_risk=float(arguments.get("max_risk") or 100),
            )
    except Exception:
        logger.exception("sports_derivatives_call_crashed", extra={"bet_type": bet_type})
        return {"success": False, "error": "derivatives pricing failed"}
    if not result:
        return {"success": False, "error": "Not enough valid legs to price this bet"}
    return {"success": True, "data": result, "bet_type": bet_type}
