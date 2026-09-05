"""Pry - MCP tool definitions: sports analytics tools (stats, trends, analysis).

Split from the former ``pry_mcp/tools/sports.py`` god file. Holds the
analytics-domain candidate registry (``_SPORTS_TOOL_FNS``) for historical
odds, betting percentages, sharp consensus, and alerts. These tools land
from parallel agents; no static ``PRY_TOOLS`` schemas exist yet, so the
list is empty and the registry is guarded.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any

# No analytics tool schemas have landed yet — the analytics tools are
# dispatched purely through the guarded candidate registry below.
PRY_TOOLS: list[dict[str, Any]] = []

# ── Sports analytics candidate registry (guarded) ─────────────────────
# Money-printer tools land from parallel agents (historical_odds,
# betting_percentages, sharp_consensus, alerts). Each maps to one or more
# (module, candidate-callables) options so the landed module/function name
# is resolved defensively, mirroring the arbitrage/plus_ev pattern.
_SPORTS_TOOL_FNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "pry_historical_odds": (
        ("historical", ("get_historical_odds", "historical_odds", "get_historical")),
        ("historical_odds", ("get_historical_odds", "historical_odds", "get_historical")),
    ),
    "pry_betting_percentages": (
        (
            "betting_percentages",
            ("get_betting_percentages", "betting_percentages", "get_percentages"),
        ),
        ("percentages", ("get_betting_percentages", "betting_percentages", "get_percentages")),
    ),
    "pry_sharp_consensus": (
        ("sharp_consensus", ("get_sharp_consensus", "sharp_consensus", "get_consensus")),
        ("consensus", ("get_sharp_consensus", "sharp_consensus", "get_consensus")),
    ),
    "pry_alerts": (
        ("alerts", ("list_alerts", "get_alerts", "alerts")),
        ("alert", ("list_alerts", "get_alerts", "alerts")),
    ),
}
