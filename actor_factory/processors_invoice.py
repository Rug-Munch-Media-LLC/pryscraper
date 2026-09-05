"""Pry - Apify Actor Factory: invoice extractor.

Accounting-field extraction (vendor, number, dates, totals) from invoice
documents parsed to text by the engine's PDF tier.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import re
from typing import Any

from actor_factory.processors_common import _base_item

_INVOICE_TOTAL_RE = re.compile(
    r"(?:grand\s+total|total\s+due|amount\s+due|invoice\s+total|balance\s+due|total)\s*[:\-]?\s*"
    r"(?P<cur>[A-Z]{3}|[$€£¥])?\s*(?P<amt>[\d.,]+)",
    re.I,
)
_INVOICE_DATE_RE = re.compile(
    r"(?:invoice\s+date|date(?:d)?|issue\s+date)\s*[:\-]?\s*"
    r"(?P<d>\d{1,4}[./-]\d{1,2}[./-]\d{1,4})",
    re.I,
)
_INVOICE_NUMBER_RE = re.compile(r"invoice\s*(?:number|no\.?|#)\s*[:\-]?\s*([A-Z0-9-]{3,30})", re.I)


def process_invoice(
    url: str, result: dict[str, Any], options: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    """Extract accounting fields (vendor, number, dates, totals) from
    invoice documents parsed to text by the engine's PDF tier."""
    item = _base_item(url, result)
    if item["status"] != "ok":
        return item
    text = item["content"] or ""
    total_m = None
    for m in _INVOICE_TOTAL_RE.finditer(text):
        total_m = m  # last match wins: grand total usually printed last
    date_m = _INVOICE_DATE_RE.search(text)
    number_m = _INVOICE_NUMBER_RE.search(text)
    if not any([total_m, date_m, number_m]):
        item["status"] = "skipped"
        item["error"] = "no invoice fields detected in document text"
        item.pop("content", None)
        return item
    item.pop("content", None)
    item["invoice"] = {
        "number": number_m.group(1) if number_m else "",
        "date": date_m.group("d") if date_m else "",
        "total": total_m.group("amt") if total_m else "",
        "currency": (total_m.group("cur") if total_m else "") or "",
        "vendor_hint": (text.split("\n")[0][:80] if text else "").strip(),
    }
    return item
