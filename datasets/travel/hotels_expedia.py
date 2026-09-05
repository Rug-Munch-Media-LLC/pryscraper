"""Pry — travel hotels: Expedia extraction (JSON-LD structured data).

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
from datasets.travel.hotels_common import _CURRENCY_RE

_LD_JSON_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


def _extract_json_ld(html: str) -> list[Any]:
    """Parse every ``application/ld+json`` block on a page (never raises)."""
    blocks: list[Any] = []
    for match in _LD_JSON_RE.finditer(html):
        body = match.group(1).strip()
        if not body:
            continue
        try:
            parsed = json.loads(body)
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
        if isinstance(parsed, list):
            blocks.extend(parsed)
        elif isinstance(parsed, dict):
            blocks.append(parsed)
    return blocks


def _ld_price(obj: dict[str, Any]) -> int | None:
    """Best-effort per-night price from a JSON-LD hotel/offer node."""
    offers = obj.get("offers")
    if isinstance(offers, dict):
        price = offers.get("price")
        if isinstance(price, (int, float)) and 20 <= price <= 100_000:
            return int(price)
        spec = offers.get("priceSpecification")
        if isinstance(spec, dict):
            price = spec.get("price")
            if isinstance(price, (int, float)) and 20 <= price <= 100_000:
                return int(price)
    price = obj.get("price")
    if isinstance(price, (int, float)) and 20 <= price <= 100_000:
        return int(price)
    return None


def _find_expedia_rates(html: str) -> list[dict[str, Any]]:
    """Locate hotel-rate records in an Expedia page's JSON-LD blocks."""
    rates: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for obj in _walk_dicts(_extract_json_ld(html)):
        name = obj.get("name")
        if not isinstance(name, str):
            continue
        name = name.strip()
        if not (2 <= len(name) <= 80) or "\n" in name:
            continue
        price = _ld_price(obj)
        if price is None:
            continue
        currency = str(obj.get("priceCurrency") or obj.get("currency") or "USD").upper()
        if not _CURRENCY_RE.fullmatch(currency):
            currency = "USD"
        key = (name, price)
        if key in seen:
            continue
        seen.add(key)
        rates.append(
            {
                "hotel": name,
                "price_per_night": price,
                "currency": currency,
                "total": None,
            }
        )
    rates.sort(key=lambda entry: (entry["price_per_night"], entry["hotel"]))
    return rates
