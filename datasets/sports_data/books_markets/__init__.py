"""Stable facade for sportsbook JSON market extraction."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from datasets.sports_data.books_markets.helpers import (
    _event_teams,
    _is_draw_name,
    _iter_dicts,
    _market_key,
    _normalize_market_key,
    _outcome_groups,
    _outcome_price,
    _price_for,
)
from datasets.sports_data.books_markets.records import (
    _h2h_record,
    _records_for_outcome_group,
    _spread_record,
    _total_record,
)
from datasets.sports_data.books_markets.walker import (
    _pair_odds,
    _records_from_dict,
    _three_way_odds,
    _walk_json,
)

__all__ = [
    "_event_teams",
    "_h2h_record",
    "_is_draw_name",
    "_iter_dicts",
    "_market_key",
    "_normalize_market_key",
    "_outcome_groups",
    "_outcome_price",
    "_pair_odds",
    "_price_for",
    "_records_for_outcome_group",
    "_records_from_dict",
    "_spread_record",
    "_three_way_odds",
    "_total_record",
    "_walk_json",
]
