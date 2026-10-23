# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Emitter payloads (signal half) for the 2026-10-23 schema alignment.

Shapes come from the handlers that write them: ``cheapest_date_grid``,
``get_resale_prices``, ``get_new_tokens`` (+ ``_with_created_alias``),
``get_headlines``, ``get_sentiment`` (``mentions_timeline`` is
``_bucket_daily``'s ``{date, count, avg_tone}``), ``get_forecast``,
``get_prediction_market``, ``get_lineups`` (documented record),
``get_props_vs_matchup`` and ``get_sharp_report``.
"""

from __future__ import annotations

from typing import Any

SIGNAL_PAYLOADS: dict[str, Any] = {
    "pry_flights_grid": [
        {"date": "2026-09-01", "price": 412.0, "airline": "AF", "duration": 435, "stops": 0}
    ],
    "pry_resale": [
        {
            "marketplace": "StubHub",
            "section": "101",
            "row": "12",
            "listing_price": 245.0,
            "quantity": 2,
            "last_update": "2026-10-23T10:00:00+00:00",
        }
    ],
    "pry_token_launches": [
        {
            "chain": "solana",
            "address": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
            "symbol": "BONK",
            "name": "Bonk",
            "pair_address": "8qbHbw2BbbTHBW1sbeqakYXVKRQM8Ne7pLK7m6CVfeR",
            "created_at_utc": "2026-10-23T09:00:00Z",
            "created_at": "2026-10-23T09:00:00Z",
            "price_usd": 0.00002,
            "liquidity_usd": 1200000.0,
            "volume_24h_usd": 540000.0,
            "price_change_24h_pct": 12.5,
            "source": "dexscreener",
        }
    ],
    "pry_news": [
        {
            "title": "Senate advances market-structure bill",
            "url": "https://www.reuters.com/technology/x",
            "source": "Reuters",
            "domain": "reuters.com",
            "published": "2026-10-23T08:00:00+00:00",
            "image": "https://www.reuters.com/resizer/x.jpg",
        }
    ],
    "pry_sentiment": {
        "query": "Bitcoin ETF",
        "avg_tone": 1.4,
        "positive_pct": 42.0,
        "negative_pct": 18.0,
        "articles": 120,
        "mentions_timeline": [{"date": "2026-10-22", "count": 14, "avg_tone": 1.1}],
    },
    "pry_weather": {
        "location": {"lat": 38.9072, "lon": -77.0369, "city": "Washington", "state": "DC"},
        "current": {
            "temp_f": 61.0,
            "condition": "Clear",
            "wind_mph": 5.0,
            "humidity_pct": 55.0,
            "observed_at": "2026-10-23T10:00:00+00:00",
        },
        "forecast": [
            {
                "date": "2026-10-24",
                "high_f": 68.0,
                "low_f": 52.0,
                "condition": "Sunny",
                "precip_pct": 0.0,
            }
        ],
        "alerts": [],
    },
    "pry_prediction_market_detail": {
        "market_id": "0x1f2e3d",
        "source": "polymarket",
        "question": "Will the Fed cut rates in December?",
        "category": "Economics",
        "outcomes": [{"name": "Yes", "price": 0.62}, {"name": "No", "price": 0.38}],
        "yes_price": 0.62,
        "no_price": 0.38,
        "volume": 120000.0,
        "liquidity": 34000.0,
        "resolution_date": "2026-12-18",
        "url": "https://polymarket.com/event/fed-december",
        "active": True,
        "last_update": "2026-10-23T10:00:00+00:00",
    },
    "pry_lineups": {
        "team": "Los Angeles Lakers",
        "team_id": "13",
        "sport": "nba",
        "event": "Lakers vs Celtics",
        "event_id": "401772301",
        "starters": [{"id": "1966", "name": "LeBron James", "position": "F"}],
        "bench": [{"id": "4066", "name": "Austin Reaves", "position": "G"}],
        "probable": [],
        "questionable": [{"name": "Anthony Davis", "status": "questionable"}],
        "out": [{"name": "Jarred Vanderbilt", "status": "out"}],
        "minutes_projection": {"LeBron James": 34.5},
        "source": "espn",
    },
    "pry_props_matchup": {
        "sport": "nba",
        "event": "Celtics @ Lakers",
        "event_id": "401772301",
        "home_team": "Los Angeles Lakers",
        "away_team": "Boston Celtics",
        "props": [
            {
                "player": "LeBron James",
                "sport": "nba",
                "prop_type": "player_points",
                "line": 25.5,
                "over_odds": -110,
                "under_odds": -110,
                "book": "draftkings",
                "movement": "steady",
                "source": "the_odds_api",
            }
        ],
        "defense": {"Los Angeles Lakers": {"player_points": {"rank": 5, "grade": "tough"}}},
        "source": "the_odds_api",
    },
    "pry_sharp_report": {
        "sport": "nba",
        "generated_at": "2026-10-23T10:00:00+00:00",
        "steam_moves_count": 1,
        "rlm_signals": 1,
        "top_divergences": [{"event": "Celtics @ Lakers"}],
        "line_watch_items": 0,
        "steam_moves": [{"event": "Celtics @ Lakers"}],
        "rlm": [{"event": "Celtics @ Lakers"}],
        "overall_sharp_indicators": [{"event": "Celtics @ Lakers", "signals": ["steam_move"]}],
    },
}
