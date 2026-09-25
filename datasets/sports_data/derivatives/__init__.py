"""Stable pricing facade for sportsbook derivative math.

The implementation is split by responsibility; these imports preserve the
historical ``datasets.sports_data.derivatives`` API.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from datasets.sports_data.derivatives.if_bets import price_if_bet
from datasets.sports_data.derivatives.odds_math import (
    american_to_decimal,
    decimal_to_american,
    effective_decimal,
    parlay_decimal,
)
from datasets.sports_data.derivatives.reverse_bets import price_reverse_bet
from datasets.sports_data.derivatives.round_robin import price_round_robin
from datasets.sports_data.derivatives.teasers import price_teaser

__all__ = [
    "american_to_decimal",
    "decimal_to_american",
    "effective_decimal",
    "parlay_decimal",
    "price_if_bet",
    "price_reverse_bet",
    "price_round_robin",
    "price_teaser",
]
