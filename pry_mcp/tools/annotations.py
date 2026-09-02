"""Pry - MCP tool definitions: MCP tool annotation hints..

Split from the former monolithic ``pry_mcp/tools.py`` god file.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

# ── MCP 2025-11-25 tool annotations ────────────────────────────────────
# Every tool must declare ``readOnlyHint`` / ``destructiveHint`` /
# ``idempotentHint`` so clients (Claude, Cursor, Hermes, agent SDKs) can
# reason about side effects before calling. Defaults: read-only (no server
# state mutation), non-destructive, idempotent (repeated calls are safe).
# Tools that mutate server state opt out explicitly.
#
# Audit (2026-08-17, all 73 PRY_TOOLS):
#   * pry_monitor  — persists a scheduled monitor on the server:
#     readOnlyHint=False, idempotentHint=False. destructiveHint stays False:
#     it never deletes data (removal is a separate /v1/monitor/{id} DELETE).
#   * pry_referrals — audited: GET /v1/referrals/catalog reads the static
#     PROVIDER_CATALOG; it does NOT record clicks/conversions
#     (ReferralTracker.record_click is a different route), so it keeps the
#     read-only, idempotent default.
#   * The 7 sports-betting tools (pry_odds, pry_arbitrage, pry_plus_ev,
#     pry_props, pry_injuries, pry_live_odds, pry_scores) are pure reads of
#     The Odds API / ESPN feeds — no server-state changes, so they keep the
#     default read-only, non-destructive, idempotent annotations.
#   * The 4 new money-printer sports tools (pry_historical_odds,
#     pry_betting_percentages, pry_sharp_consensus, pry_alerts) are pure
#     reads of odds/history/consensus feeds — same default annotations.
#   * The 4 new coverage tools (pry_books, pry_book_coverage,
#     pry_scrape_methods, pry_all_sources) are pure reads of the 112-book
#     sportsbook registry / multi-source odds feeds — same default
#     read-only, non-destructive, idempotent annotations.
#   * The climate/research tools (pry_weather, pry_agri, pry_papers,
#     pry_domain) are pure reads of public weather/academic/WHOIS feeds —
#     same default read-only, non-destructive, idempotent annotations.
#   * The 8 new events/freight/energy/food/supply tools (pry_events,
#     pry_resale, pry_freight, pry_energy_lmp, pry_grocery, pry_restaurant,
#     pry_imports, pry_firmographics) are pure reads of public ticket /
#     freight / energy / retail / customs feeds — same default annotations.
#   * The 2 new bidding tools (pry_contracts, pry_grants) are pure reads of
#     public government procurement / grant feeds — same default read-only,
#     non-destructive, idempotent annotations.
#   * The remaining 33 tools are reads/scrapes with no server-state changes —
#     the default read-only, non-destructive, idempotent annotations apply.
_TOOL_ANNOTATIONS: dict[str, dict[str, bool]] = {
    # pry_monitor persists a scheduled monitor on the server.
    "pry_monitor": {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
    },
}


def _annotations_for(name: str) -> dict[str, bool]:
    """Return the MCP annotation triple for a tool name (default: read-only)."""
    if name in _TOOL_ANNOTATIONS:
        return _TOOL_ANNOTATIONS[name]
    return {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True}
