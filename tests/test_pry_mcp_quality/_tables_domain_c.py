# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Domain round-trip table (part C): sports betting intelligence tools
(23 new tools, 2026-09-05) and mega_search."""

from __future__ import annotations

from typing import Any

DOMAIN_TOOLS_C: dict[str, tuple[str, tuple[str, ...], dict[str, Any]]] = {
    # ── Sports betting intelligence (23 new tools, 2026-09-05) ──
    # prediction_markets tools go through the sports dispatcher with
    # module_name "prediction_markets" — the dispatcher imports
    # sports_data.prediction_markets which re-exports from datasets.prediction_markets
    "pry_prediction_markets": (
        "sports_data.prediction_markets_reexport",
        ("get_prediction_markets",),
        {"limit": 20},
    ),
    "pry_prediction_market_detail": (
        "sports_data.prediction_markets_reexport",
        ("get_prediction_market",),
        {"market_id": "test"},
    ),
    "pry_futures": (
        "sports_data.futures",
        ("get_futures_odds",),
        {"limit": 20},
    ),
    "pry_derivatives": (
        "sports_data.derivatives",
        ("price_teaser",),
        {"bet_type": "teaser"},
    ),
    "pry_kelly_criterion": (
        "sports_data.bankroll",
        ("optimal_stake",),
        {"win_prob": 0.55, "decimal_odds": 2.0},
    ),
    "pry_lineups": (
        "sports_data.player_intel",
        ("get_lineups",),
        {"team": "Lakers"},
    ),
    "pry_player_props_live": (
        "sports_data.player_intel",
        ("get_player_props_live",),
        {"player_name": "LeBron"},
    ),
    "pry_player_stats": (
        "sports_data.player_intel",
        ("get_player_recent_stats",),
        {"player_name": "LeBron"},
    ),
    "pry_props_matchup": (
        "sports_data.player_intel",
        ("get_props_vs_matchup",),
        {"home_team": "Lakers", "away_team": "Celtics"},
    ),
    "pry_steam_moves": (
        "sports_data.sharp_intel",
        ("get_steam_moves",),
        {},
    ),
    "pry_reverse_line_movement": (
        "sports_data.sharp_intel",
        ("get_reverse_line_movement",),
        {},
    ),
    "pry_bet_money_divergence": (
        "sports_data.sharp_intel",
        ("get_bet_vs_money_divergence",),
        {},
    ),
    "pry_line_watch": (
        "sports_data.sharp_intel",
        ("get_line_watch",),
        {},
    ),
    "pry_sharp_report": (
        "sports_data.sharp_intel",
        ("get_sharp_report",),
        {},
    ),
    "pry_live_games": (
        "sports_data.live_intel",
        ("get_live_games",),
        {},
    ),
    "pry_live_game_state": (
        "sports_data.live_intel",
        ("get_live_game_state",),
        {"event_id": "test"},
    ),
    "pry_live_win_probability": (
        "sports_data.live_intel",
        ("get_live_win_probability",),
        {"event_id": "test"},
    ),
    "pry_live_scoring": (
        "sports_data.live_intel",
        ("get_live_scoring_breakdown",),
        {"event_id": "test"},
    ),
    "pry_live_betting_impact": (
        "sports_data.live_intel",
        ("get_live_betting_impact",),
        {"event_id": "test"},
    ),
    "pry_game_weather": (
        "sports_data.game_context",
        ("get_game_weather",),
        {"lat": 40.0, "lon": -74.0},
    ),
    "pry_weather_impact": (
        "sports_data.game_context",
        ("get_weather_impact",),
        {"lat": 40.0, "lon": -74.0},
    ),
    "pry_game_context": (
        "sports_data.game_context",
        ("get_game_context",),
        {"lat": 40.0, "lon": -74.0, "home_team": "Giants", "away_team": "Cowboys"},
    ),
    "pry_mega_search": (
        "pry.engine.mega_search",
        ("mega_search",),
        {"query": "test", "num_results": 3},
    ),
}
