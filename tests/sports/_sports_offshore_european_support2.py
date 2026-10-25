from __future__ import annotations

from typing import Any


def _betfair_markets_payload() -> dict[str, Any]:
    return {
        "eventTypes": [
            {
                "eventNodes": [
                    {
                        "event": {"name": "Lakers v Celtics"},
                        "marketNodes": [
                            {
                                "marketId": "1.200123456",
                                "marketName": "Match Odds",
                                "runners": [
                                    {
                                        "runnerName": "Los Angeles Lakers",
                                        "exchange": {"availableToBack": [{"price": 2.10}]},
                                    },
                                    {
                                        "runnerName": "Boston Celtics",
                                        "exchange": {"availableToBack": [{"price": 1.85}]},
                                    },
                                ],
                            }
                        ],
                    }
                ]
            }
        ]
    }

def _blocked_html() -> str:
    return "<html><body>Just a moment... checking your browser</body></html>"

def _record(**kw: Any) -> dict[str, Any]:
    """Canonical odds record with sensible defaults."""
    base: dict[str, Any] = {
        "sport": "basketball_nba",
        "event": "Celtics @ Lakers",
        "event_id": "evt-1",
        "market": "h2h",
        "book": "bookmaker",
        "bookmaker": "BookMaker",
        "home": "Los Angeles Lakers",
        "away": "Boston Celtics",
        "home_odds": 2.10,
        "away_odds": 1.85,
        "draw_odds": None,
        "spread": None,
        "total": None,
        "last_update": None,
        "source": "offshore",
    }
    base.update(kw)
    return base

def _schema_keys() -> set[str]:
    return {
        "sport",
        "event",
        "event_id",
        "market",
        "book",
        "bookmaker",
        "home",
        "away",
        "home_odds",
        "away_odds",
        "draw_odds",
        "spread",
        "total",
        "last_update",
        "source",
    }
