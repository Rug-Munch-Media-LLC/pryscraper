"""Pry - MCP tool definitions: sharp money intelligence tools.

Holds the sharp-money tool schemas (``PRY_TOOLS``) and the guarded candidate
registry (``_SHARP_TOOL_FNS``) for steam moves / reverse line movement /
bet-vs-money divergence / line watch / sharp report / sharp consensus,
backed by ``datasets.sports_data.sharp_intel``.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

_SPORT_DESCRIPTION = (
    "Sport: nba, nfl, mlb, nhl, ncaab, ncaaf, epl, mls, wnba, ufc, cfl (default: nba)"
)

PRY_TOOLS: list[dict[str, Any]] = [
    {
        "name": "pry_steam_moves",
        "description": (
            "Detect steam moves: lines that shifted across 3+ sportsbooks "
            "simultaneously inside a short lookback window — the loudest sharp "
            "money signal, since independent books rarely move in lockstep "
            "without a syndicate behind it. Each record includes the event, "
            "outcome, old/new line, books that moved, move direction and "
            "magnitude, and a confidence score (high when 5+ books moved "
            "together). "
            "Use to follow professional money in real time, e.g. 'any steam on "
            "tonight's NBA slate?' or call with lookback_minutes=30 right "
            "before tip-off to catch late sharp hits."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sport": {
                    "type": "string",
                    "default": "nba",
                    "description": _SPORT_DESCRIPTION,
                },
                "lookback_minutes": {
                    "type": "integer",
                    "default": 60,
                    "minimum": 1,
                    "maximum": 180,
                    "description": (
                        "Window in minutes for comparing the earliest vs latest "
                        "recorded odds snapshot (default: 60). Poll repeatedly "
                        "for meaningful windows — history is in-memory."
                    ),
                },
            },
            "required": [],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "event": {"type": "string"},
                            "event_id": {"type": "string"},
                            "market": {"type": "string"},
                            "outcome": {"type": "string"},
                            "old_line": {"type": "number"},
                            "new_line": {"type": "number"},
                            "books_moved": {"type": "array", "items": {"type": "string"}},
                            "move_direction": {"type": "string", "enum": ["up", "down"]},
                            "move_magnitude": {"type": "number"},
                            "timestamp": {"type": "string"},
                            "confidence": {"type": "string", "enum": ["high", "medium"]},
                        },
                    },
                },
                "sport": {"type": "string"},
                "lookback_minutes": {"type": "integer"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_reverse_line_movement",
        "description": (
            "Find reverse line movement (RLM): lines that moved TOWARD the side "
            "with LESS public betting percentage — the classic sign that sharp "
            "money is fading the public. Each record includes the event, side, "
            "public bet %, line movement direction, whether the RLM signal "
            "fired, and a strength rating based on % divergence and move size. "
            "Requires a configured public betting-percentage feed "
            "(PRY_SHARP_BET_FEED); without it no signal is fabricated. "
            "Use to bet against the public when the line agrees with sharps, "
            "e.g. 'show RLM signals on the NFL slate' or call with sport='nba' "
            "before lineups lock."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sport": {
                    "type": "string",
                    "default": "nba",
                    "description": _SPORT_DESCRIPTION,
                },
            },
            "required": [],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "event": {"type": "string"},
                            "event_id": {"type": "string"},
                            "sport": {"type": "string"},
                            "side": {"type": "string", "enum": ["home", "away"]},
                            "public_bet_pct": {"type": "number"},
                            "line_movement": {"type": "string", "enum": ["toward", "away"]},
                            "line_move_pct": {"type": "number"},
                            "rlm_signal": {"type": "boolean"},
                            "strength": {"type": "string", "enum": ["strong", "moderate", "weak"]},
                        },
                    },
                },
                "sport": {"type": "string"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_bet_money_divergence",
        "description": (
            "Find bet-percentage vs money-percentage divergence: when a large "
            "share of TICKETS is on one team but the MONEY (dollars) is on the "
            "other, big bettors are on the minority side. Each record includes "
            "the event, side, bet %, money %, divergence (money minus bets), "
            "the identified sharp side, and a confidence rating. "
            "Requires a configured public betting-percentage feed "
            "(PRY_SHARP_BET_FEED). "
            "Use to spot where the wiseguy money disagrees with the public, "
            "e.g. 'where are sharps on the opposite side of the public in the "
            "NFL?' or call with sport='nba' for the full slate."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sport": {
                    "type": "string",
                    "default": "nba",
                    "description": _SPORT_DESCRIPTION,
                },
            },
            "required": [],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "event": {"type": "string"},
                            "event_id": {"type": "string"},
                            "sport": {"type": "string"},
                            "side": {"type": "string", "enum": ["home", "away"]},
                            "bet_pct": {"type": "number"},
                            "money_pct": {"type": "number"},
                            "divergence": {"type": "number"},
                            "sharp_side": {"type": ["string", "null"]},
                            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                        },
                    },
                },
                "sport": {"type": "string"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_line_watch",
        "description": (
            "Lines worth watching for value: current vs opening line per "
            "event, which book currently holds the best number, total movement "
            "since the first recorded snapshot, and a value indicator "
            "(good_line / fair_line / bad_line) comparing the best price "
            "against the market consensus. "
            "Use to shop for the best available number before betting, e.g. "
            "'which book has the best NBA moneyline prices right now?' or call "
            "with sport='nfl' to build a line-shopping dashboard."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sport": {
                    "type": "string",
                    "default": "nba",
                    "description": _SPORT_DESCRIPTION,
                },
            },
            "required": [],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "event": {"type": "string"},
                            "event_id": {"type": "string"},
                            "sport": {"type": "string"},
                            "market": {"type": "string"},
                            "current_line": {"type": "number"},
                            "opening_line": {"type": "number"},
                            "movement": {"type": "number"},
                            "best_line": {
                                "type": "object",
                                "properties": {
                                    "book": {"type": "string"},
                                    "price": {"type": "number"},
                                },
                            },
                            "value_indicator": {
                                "type": "string",
                                "enum": ["good_line", "fair_line", "bad_line"],
                            },
                        },
                    },
                },
                "sport": {"type": "string"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_sharp_report",
        "description": (
            "Full sharp money intelligence report for a sport: aggregates "
            "steam moves, reverse line movement signals, top bet/money "
            "divergences, line-watch items, and an overall sharp-indicators "
            "ranking of which games professional money is on. "
            "Use as a one-call daily briefing before betting, e.g. 'give me "
            "the sharp money report for tonight's NBA games' or call with "
            "sport='nfl' on Sunday morning for the week's sharpest angles."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sport": {
                    "type": "string",
                    "default": "nba",
                    "description": _SPORT_DESCRIPTION,
                },
            },
            "required": [],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "object",
                    "properties": {
                        "sport": {"type": "string"},
                        "generated_at": {"type": "string"},
                        "steam_moves_count": {"type": "integer"},
                        "rlm_signals": {"type": "integer"},
                        "top_divergences": {"type": "array", "items": {"type": "object"}},
                        "line_watch_items": {"type": "integer"},
                        "steam_moves": {"type": "array", "items": {"type": "object"}},
                        "rlm": {"type": "array", "items": {"type": "object"}},
                        "overall_sharp_indicators": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "event": {"type": "string"},
                                    "signals": {"type": "array", "items": {"type": "string"}},
                                },
                            },
                        },
                    },
                },
                "sport": {"type": "string"},
            },
            "required": ["success"],
        },
    },
    {
        "name": "pry_sharp_consensus",
        "description": (
            "Games where MULTIPLE sharp indicators align on the same side: "
            "steam moves, reverse line movement, and bet/money divergence all "
            "pointing at one team. Each record includes the event, which "
            "indicators fired, the consensus sharp pick, a confidence level "
            "(high when 3+ indicators agree), and a recommended bet summary. "
            "Use for the highest-conviction plays only, e.g. 'which games have "
            "the strongest sharp consensus tonight?' or call with sport='nba' "
            "to filter the slate down to multi-signal games."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sport": {
                    "type": "string",
                    "default": "nba",
                    "description": _SPORT_DESCRIPTION,
                },
            },
            "required": [],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "event": {"type": "string"},
                            "event_id": {"type": "string"},
                            "sport": {"type": "string"},
                            "indicators": {"type": "array", "items": {"type": "string"}},
                            "sharp_pick": {"type": ["string", "null"]},
                            "confidence_level": {
                                "type": "string",
                                "enum": ["high", "medium", "low"],
                            },
                            "recommended_bet": {"type": "string"},
                        },
                    },
                },
                "sport": {"type": "string"},
            },
            "required": ["success"],
        },
    },
]

# ── Sharp-intel candidate registry (guarded) ──────────────────────────
# Maps each tool to (module, candidate-callables) options tried in order,
# matching the dispatcher convention used by pry_mcp/tools/sports_betting.py.
_SHARP_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_steam_moves": (("sharp_intel", ("get_steam_moves",)),),
    "pry_reverse_line_movement": (("sharp_intel", ("get_reverse_line_movement",)),),
    "pry_bet_money_divergence": (("sharp_intel", ("get_bet_vs_money_divergence",)),),
    "pry_line_watch": (("sharp_intel", ("get_line_watch",)),),
    "pry_sharp_report": (("sharp_intel", ("get_sharp_report",)),),
    "pry_sharp_consensus": (("sharp_intel", ("get_consensus_sharp_picks",)),),
}
