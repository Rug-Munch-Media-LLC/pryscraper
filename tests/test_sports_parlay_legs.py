# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
import asyncio
import math
from typing import Any

from datasets.sports_data import parlay_legs as legs, parlay_math as pure, parlays as facade


def _edge(
    market: str,
    side: str,
    odds: float = 2.0,
    fair: float = 0.6,
    book: str = "book-a",
    **extra: Any,
) -> dict[str, Any]:
    return {
        "market": market,
        "side": side,
        "player": None,
        "team": None,
        "line": None,
        "odds": odds,
        "implied_prob": 1.0 / odds,
        "fair_prob": fair,
        "label": side,
        "book": book,
        **extra,
    }


class TestExtraction:
    def test_team_name_fallback_prefers_event_then_h2h_outcomes(self) -> None:
        assert legs._comparison_team_names({"event": "Celtics @ Lakers"}) == (
            "Lakers",
            "Celtics",
        )
        fallback = {
            "event": "",
            "bookmakers": [
                {
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [{"name": "Lakers"}, {"name": "Celtics"}],
                        }
                    ]
                }
            ],
        }
        assert legs._comparison_team_names(fallback) == ("Lakers", "Celtics")

    def test_extracts_h2h_spread_total_and_prop_classes(self) -> None:
        h2h = legs._market_legs_from_outcomes(
            "h2h",
            [{"name": "Lakers", "price": 1.91}, {"name": "Celtics", "price": 1.91}],
            "Lakers",
            "Celtics",
            "sharp",
        )
        spread = legs._market_legs_from_outcomes(
            "spreads",
            [
                {"name": "Lakers", "price": 1.91, "point": -3.5},
                {"name": "Celtics", "price": 1.91, "point": 3.5},
            ],
            "Lakers",
            "Celtics",
            "sharp",
        )
        total = legs._market_legs_from_outcomes(
            "totals",
            [
                {"name": "Over", "price": 1.91, "point": 224.5},
                {"name": "Under", "price": 1.91, "point": 224.5},
            ],
            None,
            None,
            "sharp",
        )
        props = legs._prop_legs_from_records(
            [
                {
                    "book": "sharp",
                    "player": "LeBron",
                    "team": "Lakers",
                    "market": "player_points",
                    "line": 25.5,
                    "over_odds": 1.91,
                    "under_odds": 1.91,
                }
            ],
            "sharp",
        )
        assert [leg["market"] for leg in h2h] == ["h2h", "h2h"]
        assert [leg["side"] for leg in spread] == ["home", "away"]
        assert [(leg["side"], leg["line"]) for leg in total] == [("over", 224.5), ("under", 224.5)]
        assert [(leg["side"], leg["fair_prob"]) for leg in props] == [("over", 0.5), ("under", 0.5)]
        assert [leg["implied_prob"] for leg in h2h] == [0.52356, 0.52356]

    def test_best_pool_anchors_team_markets_on_sharpest_book(self) -> None:
        grouped = {
            "h2h": [
                _edge("h2h", "home", 1.8, 0.53, "soft"),
                _edge("h2h", "away", 1.8, 0.53, "soft"),
                _edge("h2h", "home", 1.9, 0.51, "sharp"),
                _edge("h2h", "away", 1.9, 0.51, "sharp"),
            ]
        }
        pool = legs._best_leg_pool(grouped)
        assert len(pool) == 2
        assert {leg["book"] for leg in pool} == {"sharp"}
        assert {leg["odds"] for leg in pool} == {1.9}
        assert {leg["fair_prob"] for leg in pool} == {0.5}


class TestScanAndPricing:
    def test_scan_is_cross_class_and_orders_ev_descending(self) -> None:
        pool = [
            _edge("player_rebounds", "over", 2.0, 0.6, "book-c", player="A"),
            _edge("total", "under", 2.0, 0.6, "book-b"),
            _edge("h2h", "home", 2.0, 0.7, "book-a", team="Home"),
        ]
        edges = legs._scan_pool(
            pool, event_id="nba:1", event="Away @ Home", sport="nba", threshold=-1
        )
        assert len(edges) == 3
        assert [edge["ev_pct"] for edge in edges] == [68.0, 68.0, 44.0]
        assert {(edge["legs"][0]["market"], edge["legs"][1]["market"]) for edge in edges} == {
            ("player_rebounds", "total"),
            ("player_rebounds", "h2h"),
            ("total", "h2h"),
        }

    def test_caps_pool_and_pair_enumeration(self) -> None:
        same_class = [_edge("h2h", f"team-{i}") for i in range(legs._MAX_POOL_LEGS)]
        ignored_tail = _edge("player_points", "over", player="tail")
        assert (
            legs._scan_pool(
                [*same_class, ignored_tail], event_id="", event="", sport="", threshold=-1
            )
            == []
        )

        markets = ("h2h", "total", "player_points", "alternate_spread")
        pool = [
            _edge(markets[index % len(markets)], f"side-{index}")
            for index in range(legs._MAX_POOL_LEGS)
        ]
        edges = legs._scan_pool(pool, event_id="", event="", sport="", threshold=-1)
        cross_total = sum(
            legs._different_class(left, right)
            for index, left in enumerate(pool)
            for right in pool[index + 1 :]
        )
        assert cross_total == legs._MAX_COMBOS
        assert len(edges) < cross_total

    def test_mixed_book_and_correlation_contracts(self) -> None:
        assert legs._combo_book({"book": "DK"}, {"book": "FD"}) == "mixed"
        assert legs._combo_book({"book": "DK"}, {"book": "dk"}) == "dk"
        shared_player = [
            {"market": "player_points", "player": "LeBron", "side": "over"},
            {"market": "player_rebounds", "player": "lebron", "side": "over"},
        ]
        independent = [
            {"market": "player_points", "player": "LeBron", "side": "over"},
            {"market": "player_rebounds", "player": "Curry", "side": "over"},
        ]
        assert legs._correlated(shared_player) is True
        assert legs._correlated(independent) is False

    def test_invalid_and_nonfinite_inputs_are_deterministic(self) -> None:
        for value in (None, "bad", object()):
            assert pure._to_float(value) is None
        invalid = [
            None,
            {"market": "h2h", "side": "home", "odds": "bad"},
            {"market": "h2h", "side": "home", "odds": 1.0},
            {"market": "", "side": "home", "odds": 2.0},
            {"market": "h2h", "side": "", "odds": 2.0},
        ]
        assert all(pure._normalize_leg(item, index) is None for index, item in enumerate(invalid))
        for legs_input in (math.nan, [invalid[-1] | {"odds": math.nan}]):
            result = asyncio.run(pure.build_same_game_parlay("nba:1", legs_input))
            assert isinstance(result, dict)
        infinity = [invalid[-1] | {"odds": math.inf}]
        assert isinstance(asyncio.run(pure.build_same_game_parlay("nba:1", infinity)), dict)


class TestFacadeParity:
    def test_legacy_facade_matches_split_modules(self) -> None:
        sample = [_edge("h2h", "home", 2.0, 0.5)]
        assert facade._best_leg_pool is legs._best_leg_pool
        assert facade._scan_pool is legs._scan_pool
        assert facade._normalize_leg is pure._normalize_leg
        assert facade.build_same_game_parlay is pure.build_same_game_parlay
        assert facade._best_leg_pool({"h2h": sample}) == legs._best_leg_pool({"h2h": sample})
