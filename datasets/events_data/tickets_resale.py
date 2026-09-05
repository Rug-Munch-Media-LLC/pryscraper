"""Resale marketplace (StubHub / SeatGeek) JSON-LD listing parsing.

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

from datasets.events_data.tickets_common import (
    _now_iso,
    _parse_json_ld,
    _to_float,
    _to_int,
    _walk_dicts,
)


def _map_jsonld_listing(marketplace: str, obj: dict[str, Any]) -> dict[str, Any] | None:
    """Map a JSON-LD object with an offer onto a resale listing record."""
    offers = obj.get("offers")
    if isinstance(offers, dict):
        price = _to_float(offers.get("price"))
        quantity = _to_int(offers.get("availableQuantity"))
    elif isinstance(offers, list):
        price = None
        quantity = None
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            candidate = _to_float(offer.get("price"))
            if candidate is not None:
                price = candidate
                quantity = _to_int(offer.get("availableQuantity"))
                break
    else:
        # Bare price objects only count when they carry Event/Product context
        # (the Offer dict itself must not become a separate listing).
        if not isinstance(obj.get("name"), str) or not obj.get("name"):
            return None
        price = _to_float(obj.get("price"))
        quantity = _to_int(obj.get("quantity"))
    if price is None:
        return None
    location = obj.get("location")
    section = ""
    if isinstance(location, dict) and location.get("name"):
        section = str(location["name"])
    if not section:
        section = str(obj.get("section") or "")
    row_value = obj.get("row")
    row = str(row_value) if row_value is not None else ""
    return {
        "marketplace": marketplace,
        "section": section,
        "row": row,
        "listing_price": price,
        "quantity": quantity,
        "last_update": _now_iso(),
    }


def _parse_resale_page(marketplace: str, raw: str) -> list[dict[str, Any]]:
    """Extract resale listings from JSON-LD on a marketplace search page."""
    if not raw:
        return []
    out: list[dict[str, Any]] = []
    for block in _parse_json_ld(raw):
        for d in _walk_dicts(block):
            listing = _map_jsonld_listing(marketplace, d)
            if listing:
                out.append(listing)
    return out
