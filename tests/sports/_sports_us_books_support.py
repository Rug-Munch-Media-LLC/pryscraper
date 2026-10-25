from __future__ import annotations

from typing import Any


def _dk_eventgroup_payload() -> dict[str, Any]:
    """DraftKings eventgroups shape: groupedMarkets with moneyline/spread/total."""
    return {
        "eventGroup": {"eventGroupId": 42648, "eventGroupName": "NBA"},
        "groupedMarkets": [
            {
                "event": {
                    "id": 37548622,
                    "name": "Celtics @ Lakers",
                    "startTime": "2026-11-01T00:00:00Z",
                },
                "moneyline": {
                    "markets": [
                        {
                            "outcomes": [
                                {"label": "Celtics", "oddsAmerican": 150},
                                {"label": "Lakers", "oddsAmerican": -180},
                            ]
                        }
                    ]
                },
                "spread": {
                    "markets": [
                        {
                            "outcomes": [
                                {"label": "Celtics", "line": 5.5, "oddsAmerican": -110},
                                {"label": "Lakers", "line": -5.5, "oddsAmerican": -110},
                            ]
                        }
                    ]
                },
                "total": {
                    "markets": [
                        {
                            "outcomes": [
                                {"label": "Over", "line": 224.5, "oddsAmerican": -110},
                                {"label": "Under", "line": 224.5, "oddsAmerican": -110},
                            ]
                        }
                    ]
                },
            }
        ],
    }

def _dk_main_array_payload() -> dict[str, Any]:
    """DraftKings alternate shape: ``main`` array with ``marketType`` blocks."""
    return {
        "groupedMarkets": [
            {
                "event": {"id": 1, "name": "Heat @ Knicks"},
                "main": [
                    {
                        "marketType": "MONEYLINE",
                        "outcomes": [
                            {"label": "Heat", "oddsAmerican": 200},
                            {"label": "Knicks", "oddsAmerican": -250},
                        ],
                    },
                    {
                        "marketType": "SPREAD",
                        "outcomes": [
                            {"label": "Heat", "line": 4.5, "oddsAmerican": -110},
                            {"label": "Knicks", "line": -4.5, "oddsAmerican": -110},
                        ],
                    },
                ],
            }
        ]
    }

def _fanduel_eventgroup_payload() -> dict[str, Any]:
    """FanDuel eventGroup shape: events[] with wrapped event + markets."""
    return {
        "eventGroup": {"id": 2, "name": "NBA", "regionCode": "US"},
        "events": [
            {
                "event": {
                    "id": 999,
                    "name": "Celtics @ Lakers",
                    "home": "Lakers",
                    "away": "Celtics",
                },
                "markets": [
                    {
                        "id": 1,
                        "name": "Moneyline",
                        "selections": [
                            {"name": "Celtics", "odds": {"american": 150, "decimal": 2.5}},
                            {"name": "Lakers", "odds": {"american": -180, "decimal": 1.56}},
                        ],
                    },
                    {
                        "id": 2,
                        "name": "Point Spread",
                        "selections": [
                            {
                                "name": "Celtics",
                                "handicap": 5.5,
                                "odds": {"american": -110, "decimal": 1.91},
                            },
                            {
                                "name": "Lakers",
                                "handicap": -5.5,
                                "odds": {"american": -110, "decimal": 1.91},
                            },
                        ],
                    },
                    {
                        "id": 3,
                        "name": "Total Points",
                        "selections": [
                            {
                                "name": "Over",
                                "handicap": 224.5,
                                "odds": {"american": -110, "decimal": 1.91},
                            },
                            {
                                "name": "Under",
                                "handicap": 224.5,
                                "odds": {"american": -110, "decimal": 1.91},
                            },
                        ],
                    },
                ],
            }
        ],
    }

def _fanduel_cache_payload() -> dict[str, Any]:
    """FanDuel cache/psevent shape: eventmarketgroups with price ratio."""
    return {
        "eventmarketgroups": [
            {
                "event": {"id": "555", "name": "Bulls @ Bucks"},
                "markets": [
                    {
                        "id": 1,
                        "name": "Moneyline",
                        "selections": [
                            {"name": "Bulls", "currentpriceup": 20, "currentpricedown": 23},
                            {"name": "Bucks", "currentpriceup": 20, "currentpricedown": 11},
                        ],
                    }
                ],
            }
        ]
    }
