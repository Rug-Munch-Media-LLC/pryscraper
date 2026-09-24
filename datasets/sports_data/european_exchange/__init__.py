"""Stable facade for European exchange sportsbook fetchers."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from datasets.sports_data.european_exchange.betfair import (
    _BETFAIR_AK,
    _BETFAIR_EXCHANGE,
    _BETFAIR_READONLY,
    _BETFAIR_TYPES,
    _MARKET_ID_RE,
    _discover_market_ids,
    _parse_betfair_markets,
    fetch_betfair,
)
from datasets.sports_data.european_exchange.common import _event_label
from datasets.sports_data.european_exchange.marathon import fetch_marathonbet
from datasets.sports_data.european_exchange.onexbet import (
    _decode_1xbet_payload,
    _parse_1xbet_payload,
    fetch_1xbet,
)

__all__ = [
    "_BETFAIR_AK",
    "_BETFAIR_EXCHANGE",
    "_BETFAIR_READONLY",
    "_BETFAIR_TYPES",
    "_MARKET_ID_RE",
    "_decode_1xbet_payload",
    "_discover_market_ids",
    "_event_label",
    "_parse_1xbet_payload",
    "_parse_betfair_markets",
    "fetch_1xbet",
    "fetch_betfair",
    "fetch_marathonbet",
]
