"""Characterization tests for pure-math sports derivative pricing."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

from datasets.sports_data import derivatives as public
from pry_mcp.tools.sports_derivatives import call_sports_derivatives_tool

INF = float("inf")
SPREADS = [
    {"selection": "A", "odds": -110, "type": "spread", "line": -3.5},
    {"selection": "B", "odds": -120, "type": "total", "line": 44.5},
]
SIMPLE = [
    {"selection": "A", "odds": 2.0},
    {"selection": "B", "odds": 3.0},
    {"selection": "C", "odds": 4.0},
]


class TestOddsPrimitives:
    """The eight public pricing functions retain their legacy contract."""

    def test_legacy_golden_values(self) -> None:
        assert public.american_to_decimal(-110) == 1.909091
        assert public.decimal_to_american(1.91) == -110
        assert public.parlay_decimal([2.0, 3.0]) == 6.0
        assert public.effective_decimal(300, 100) == 4.0
        assert public.price_teaser(SPREADS, 6)["direction"] == "teaser"
        assert public.price_if_bet(SIMPLE, 100)["max_win"] == 600.0
        assert public.price_reverse_bet(SIMPLE[:2], 100)["max_win"] == 600.0
        assert public.price_round_robin(SIMPLE, 2, 120)["max_win"] == 920.0

    def test_legacy_facade_matches_split_modules(self) -> None:
        from datasets.sports_data.derivatives import (
            if_bets,
            odds_math,
            reverse_bets,
            round_robin,
            teasers,
        )

        assert public.american_to_decimal(-110) == odds_math.american_to_decimal(-110)
        assert public.decimal_to_american(1.91) == odds_math.decimal_to_american(1.91)
        assert public.parlay_decimal([2.0, 3.0]) == odds_math.parlay_decimal([2.0, 3.0])
        assert public.effective_decimal(600, 100) == odds_math.effective_decimal(600, 100)
        assert public.price_teaser(SPREADS, 6) == teasers.price_teaser(SPREADS, 6)
        assert public.price_if_bet(SIMPLE, 100) == if_bets.price_if_bet(SIMPLE, 100)
        assert public.price_reverse_bet(SIMPLE, 100) == reverse_bets.price_reverse_bet(SIMPLE, 100)
        assert public.price_round_robin(SIMPLE, 2, 120) == round_robin.price_round_robin(
            SIMPLE, 2, 120
        )

    def test_conversion_and_product_properties(self) -> None:
        for decimal in (1.1, 1.5, 1.91, 2.0, 3.0, 10.0):
            american = public.decimal_to_american(decimal)
            assert public.american_to_decimal(american) == pytest.approx(decimal, abs=0.01)
        for legs in ([1.5, 2.0], [1.91, 2.0, 1.1], [3.0]):
            expected = 1.0
            for odds in legs:
                expected *= odds
            assert public.parlay_decimal(legs) == pytest.approx(expected)
        assert public.price_if_bet(SIMPLE, 0)["stake_per_leg"] == 0

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(0, 1.0), ("bad", 1.0), (math.nan, 1.0)],
    )
    def test_american_conversion_invalid_values(self, value: object, expected: float) -> None:
        assert public.american_to_decimal(value) == expected

    @pytest.mark.parametrize("value", [1.0, 0.0, -1.0, "bad"])
    def test_decimal_conversion_invalid_values(self, value: object) -> None:
        assert public.decimal_to_american(value) == 0

    def test_overflow_matches_legacy_infinity(self) -> None:
        assert public.parlay_decimal([1e308, 1e308]) == INF
        assert public.effective_decimal(1e308, 1e-308) == INF


class TestDerivativePricing:
    def test_normalization_keeps_source_index_aliases_and_drops_invalid_legs(self) -> None:
        result = public.price_teaser(
            [
                {"side": " A ", "market": " SPREAD ", "odds": -110, "line": -3.5},
                {"selection": "invalid", "odds": 0},
                {"label": " B ", "type": "h2h", "odds": 2.0},
            ],
            adjustment=6,
        )
        lines = result["adjusted_lines"]
        assert [(leg["index"], leg["selection"]) for leg in lines] == [(0, "A"), (2, "B")]
        assert (lines[0]["type"], lines[0]["adjustable"]) == ("spread", True)
        assert (lines[1]["type"], lines[1]["adjustable"]) == ("h2h", False)

    def test_teaser_and_pleaser_move_adjustable_lines_opposite_ways(self) -> None:
        teaser = public.price_teaser(SPREADS, 6, "teaser")
        pleaser = public.price_teaser(SPREADS, 6, "pleaser")
        assert (teaser["direction"], pleaser["direction"]) == ("teaser", "pleaser")
        assert teaser["combined_odds"]["decimal"] < pleaser["combined_odds"]["decimal"]
        assert teaser["adjusted_lines"][0]["adjusted_line"] < -3.5
        assert pleaser["adjusted_lines"][0]["adjusted_line"] > -3.5
        assert pleaser["adjusted_lines"][0]["adjusted_line"] == 2.5

    def test_if_bet_scenarios_and_effective_price(self) -> None:
        result = public.price_if_bet(SIMPLE, 100)
        assert len(result["scenarios"]) == 8
        assert (result["max_win"], result["max_loss"]) == (600.0, -100.0)
        assert result["effective_odds"] == {"decimal": 7.0, "american": 600}

    def test_reverse_bet_builds_both_directions(self) -> None:
        result = public.price_reverse_bet(SIMPLE[:2], 100)
        assert result["total_risk"] == 200.0
        assert [chain["direction"] for chain in result["chains"]] == ["A → B", "B → A"]
        assert (result["max_win"], result["max_loss"]) == (600.0, -200.0)

    def test_round_robin_splits_budget_across_all_combinations(self) -> None:
        result = public.price_round_robin(SIMPLE, 2, 120)
        assert (result["num_parlays"], result["total_risk"]) == (3, 120.0)
        assert result["stake_per_parlay"] == 40.0
        assert [item["profit"] for item in result["all_combinations"]] == [200.0, 280.0, 440.0]
        assert (result["max_win"], result["min_win"]) == (920.0, 200.0)

    @pytest.mark.parametrize(
        "call",
        [
            lambda: public.price_teaser(SPREADS, math.nan),
            lambda: public.price_if_bet(SIMPLE, "bad"),
            lambda: public.price_reverse_bet(None, INF),
            lambda: public.price_round_robin(SIMPLE, math.inf, 100),
        ],
    )
    def test_pricing_wrappers_return_no_raise_envelopes(self, call: Callable[[], dict]) -> None:
        assert isinstance(call(), dict)


class TestMCPDispatch:
    def test_success_envelope_matches_direct_public_pricing(self) -> None:
        cases = [
            ("teaser", SPREADS, {"adjustment": 6}, lambda: public.price_teaser(SPREADS, 6)),
            (
                "pleaser",
                SPREADS,
                {"adjustment": 6},
                lambda: public.price_teaser(SPREADS, 6, "pleaser"),
            ),
            ("if_bet", SIMPLE, {"max_risk": 100}, lambda: public.price_if_bet(SIMPLE, 100)),
            (
                "reverse",
                SIMPLE[:2],
                {"max_risk": 100},
                lambda: public.price_reverse_bet(SIMPLE[:2], 100),
            ),
            (
                "round_robin",
                SIMPLE,
                {"parlay_size": 2, "max_risk": 120},
                lambda: public.price_round_robin(SIMPLE, 2, 120),
            ),
        ]
        for bet_type, legs, options, expected_call in cases:
            envelope = call_sports_derivatives_tool({"bet_type": bet_type, "legs": legs, **options})
            assert envelope == {"success": True, "data": expected_call(), "bet_type": bet_type}

    @pytest.mark.parametrize(
        "arguments",
        [
            {"bet_type": "unknown", "legs": SIMPLE},
            {"bet_type": "if_bet", "legs": SIMPLE[:1]},
            {"bet_type": "round_robin", "legs": "not-a-list"},
            {"bet_type": "teaser", "legs": SPREADS, "adjustment": "bad"},
            {"bet_type": "reverse", "legs": SIMPLE, "max_risk": "bad"},
            {"bet_type": "if_bet", "legs": SIMPLE, "max_risk": math.nan},
        ],
    )
    def test_invalid_arguments_return_error_envelopes(self, arguments: dict) -> None:
        envelope = call_sports_derivatives_tool(arguments)
        assert (envelope["success"], isinstance(envelope["error"], str)) == (False, True)

    @pytest.mark.parametrize(
        "arguments",
        [
            {"bet_type": "teaser", "legs": SPREADS, "adjustment": INF},
            {"bet_type": "round_robin", "legs": SIMPLE, "parlay_size": INF},
            {"bet_type": "if_bet", "legs": SIMPLE, "max_risk": INF},
        ],
    )
    def test_non_finite_arguments_never_raise(self, arguments: dict) -> None:
        envelope = call_sports_derivatives_tool(arguments)
        assert (isinstance(envelope, dict), isinstance(envelope["success"], bool)) == (True, True)
