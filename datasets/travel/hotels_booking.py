"""Pry — travel hotels: Booking.com extraction (data-capla-trace JSON + regex fallback).

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
import re
from typing import Any

from datasets.travel.flights_parse import _walk_dicts
from datasets.travel.hotels_common import (
    _PRICE_RE,
    _currency_for_match,
    _extract_currency,
    _extract_hotel_name,
    _extract_price_per_night,
    _extract_total,
)


def _extract_capla_blocks(html: str) -> list[str]:
    """Pull the ``data-capla-trace`` JSON script bodies out of a page."""
    blocks: list[str] = []
    for match in re.finditer(
        r'<script[^>]*type="application/json"[^>]*data-capla-trace[^>]*>(.*?)</script>',
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        body = match.group(1).strip()
        if body:
            blocks.append(body)
    return blocks


def _find_booking_rates(html: str) -> list[dict[str, Any]]:
    """Locate hotel-rate records in a Booking.com searchresults page."""
    rates: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()

    for block in _extract_capla_blocks(html):
        try:
            payload = json.loads(block)
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
        for obj in _walk_dicts(payload):
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

    # Regex fallback: data-price attributes / $1,234-style price markers.
    for match in _PRICE_RE.finditer(html):
        raw = match.group(1) or match.group(2)
        if not raw:
            continue
        try:
            price = int(raw)
        except ValueError:
            continue
        if not (20 <= price <= 100_000):
            continue
        key = ("", price)
        if key in seen:
            continue
        seen.add(key)
        rates.append(
            {
                "hotel": "",
                "price_per_night": price,
                "currency": _currency_for_match(html, match.start()),
                "total": None,
            }
        )
    return rates
