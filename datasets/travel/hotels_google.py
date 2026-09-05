"""Pry — travel hotels: Google Hotels extraction (embedded AF_initDataCallback JSON).

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from typing import Any

from datasets.travel.flights_parse import _walk_dicts
from datasets.travel.hotels_common import (
    _extract_currency,
    _extract_hotel_name,
    _extract_price_per_night,
    _extract_total,
)


def _find_google_rates(data: Any) -> list[dict[str, Any]]:
    """Locate hotel-rate-like records in Google Hotels embedded data."""
    rates: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for obj in _walk_dicts(data):
        name = _extract_hotel_name(obj)
        if name is None:
            continue
        price = _extract_price_per_night(obj)
        if price is None:
            continue
        key = (name, price)
        if key in seen:
            continue
        seen.add(key)
        rates.append(
            {
                "hotel": name,
                "price_per_night": price,
                "currency": _extract_currency(obj),
                "total": _extract_total(obj),
            }
        )
    rates.sort(key=lambda entry: (entry["price_per_night"], entry["hotel"]))
    return rates
