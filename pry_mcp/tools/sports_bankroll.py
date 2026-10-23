"""Pry - MCP tool definition: Kelly criterion bankroll management.

Holds the ``pry_kelly_criterion`` tool schema (``PRY_TOOLS``) and the
guarded candidate registry entry (``_SPORTS_TOOL_FNS``) mapping the tool
to ``datasets.sports_data.bankroll`` callables.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

PRY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_kelly_criterion",
        "description": (
            "Kelly criterion bankroll management — optimal bet sizing from "
            "win probability and odds. Includes full/half/quarter Kelly, "
            "CLV tracking, bankroll projections, and risk-of-ruin estimation. "
            "Use to size a bet, e.g. 'how much should I stake on a 55% win "
            "probability at 2.10 odds with a $1000 bankroll?' or call with "
            "kelly_pct=0.25 for a very conservative quarter-Kelly stake."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "win_prob": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "exclusiveMinimum": 0,
                    "exclusiveMaximum": 1,
                    "description": (
                        "Estimated true win probability as a decimal "
                        "(e.g. 0.55 for 55%); must be strictly between 0 and 1"
                    ),
                },
                "decimal_odds": {
                    "type": "number",
                    "exclusiveMinimum": 1,
                    "description": (
                        "Decimal (European) odds, must be greater than 1.0 (e.g. 2.10)"
                    ),
                },
                "bankroll": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "description": "Current bankroll in currency units (e.g. 1000)",
                },
                "kelly_pct": {
                    "type": "number",
                    "default": 0.5,
                    "minimum": 0,
                    "maximum": 1,
                    "description": (
                        "Fraction of full Kelly to use: 1.0 = full Kelly, "
                        "0.5 = half-Kelly (default), 0.25 = quarter-Kelly"
                    ),
                },
                "max_bet_pct": {
                    "type": "number",
                    "default": 5.0,
                    "minimum": 0,
                    "maximum": 100,
                    "description": ("Hard cap on stake as a percentage of bankroll (default: 5.0)"),
                },
            },
            "required": ["win_prob", "decimal_odds", "bankroll"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "stake_amount": {"type": "number"},
                        "stake_pct": {"type": "number"},
                        "kelly_raw": {"type": "number"},
                        "kelly_capped": {"type": "number"},
                        "capped": {"type": "boolean"},
                        "edge": {"type": "number"},
                        "ev_per_dollar": {"type": "number"},
                        "ev_per_bet": {"type": "number"},
                        "risk_of_ruin": {"type": "number"},
                        "full_kelly_pct": {"type": "number"},
                        "confidence_interval": {
                            "type": "array",
                            "items": {"type": "number"},
                        },
                        "bankroll": {"type": "number"},
                        "valid": {"type": "boolean"},
                    },
                },
            },
            "required": ["success"],
        },
    },
]

# ── Kelly candidate registry (guarded) ────────────────────────────────
# Maps pry_kelly_criterion to the bankroll module's public callables,
# tried in order by the dispatcher.
_SPORTS_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_kelly_criterion": (
        ("bankroll", ("optimal_stake", "kelly_fraction")),
        ("kelly", ("optimal_stake", "kelly_fraction")),
    ),
}
