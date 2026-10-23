"""Pry — travel hotels: Kayak extraction (embedded __INITIAL_STATE__ JSON).

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
import logging
import re
from typing import Any
from urllib.parse import quote

from datasets.travel.flights_parse import _walk_dicts
from datasets.travel.hotels_common import _CURRENCY_RE

_KAYAK_URL = "https://www.kayak.com/hotels"

logger = logging.getLogger(__name__)


def _extract_embedded_object(html: str, marker: str) -> Any:
    """Extract the JS object/array assigned after ``marker`` (balanced scan).

    Kayak (and many React/Redux sites) embed their state as
    ``window.__INITIAL_STATE__ = {...};`` — a plain JS literal, not a
    JSON-typed script tag. The scanner walks braces with string awareness and
    decodes the captured literal. Returns ``None`` on any failure.
    """
    idx = html.find(marker)
    if idx == -1:
        return None
    start = idx + len(marker)
    while start < len(html) and html[start] not in "{[":  # allow arrays too
        start += 1
    if start >= len(html):
        return None
    opener = html[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escape = False
    i = start
    while i < len(html):
        ch = html[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    break
        i += 1
    if depth != 0:
        return None
    raw = html[start : i + 1]
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning(
            "kayak_embedded_json_invalid",
            extra={"marker": marker[:60], "error": str(exc)[:160]},
        )
        return None


def _find_kayak_rates(data: Any) -> list[dict[str, Any]]:
    """Locate hotel-rate-like records in Kayak's embedded state.

    Kayak hotel records look like ``{"name": ..., "price": {"price": <int>,
    "currency": "USD"}}``. Signature-based and best-effort, matching the
    module's layout-tolerant extraction philosophy.
    """
    rates: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for obj in _walk_dicts(data):
        name = obj.get("name")
        if not isinstance(name, str):
            continue
        name = name.strip()
        if not (2 <= len(name) <= 80) or "\n" in name:
            continue
        price_obj = obj.get("price")
        if not isinstance(price_obj, dict):
            continue
        raw_price = price_obj.get("price")
        if not isinstance(raw_price, (int, float)) or not (20 <= raw_price <= 100_000):
            continue
        price = int(raw_price)
        currency = str(price_obj.get("currency") or "").strip().upper()
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


def _kayak_search_url(name: str, checkin: str, checkout: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    if not slug:
        slug = quote(name.strip())
    return f"{_KAYAK_URL}/{slug}/{checkin}/{checkout}/2adults"
