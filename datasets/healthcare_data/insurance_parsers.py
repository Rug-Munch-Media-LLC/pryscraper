"""Rate-table HTML parsing for public insurance data.

Split out of ``insurance.py`` (god-file reduction). The ``insurance.py``
facade re-exports everything here so the surface is unchanged.

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

from lxml import etree, html as lxml_html

from datasets.healthcare_data.insurance_common import (
    _as_money,
    _contains_any,
    _looks_numeric,
    _normalize_cell,
)

_STATE_KEYWORDS = ("state", "jurisdiction", "region")
_PREMIUM_KEYWORDS = ("premium", "expenditure", "cost", "rate", "price")
_SKIP_STATES = {"total", "national average", "u.s.", "us", "united states"}
_SKIP_STATE_HEADERS = {"state", "rank", "jurisdiction", "region"}


def _parse_rate_table(html: str, page_url: str) -> list[dict[str, Any]]:
    """Parse state + premium columns out of a public rate table.

    Handles both simple tables (one state column) and the paired III tables
    that put "most expensive" and "least expensive" state data side by side
    in the same row (two state columns). Header text is gathered from the
    first two rows because the III tables use a merged-cell header layout.
    """
    try:
        doc = lxml_html.fromstring(html)
    except (ValueError, etree.ParserError):
        return []
    for table in doc.xpath("//table"):
        row_elements = table.xpath(".//tr")
        if len(row_elements) < 2:
            continue
        header_rows: list[list[str]] = []
        for tr in row_elements[:2]:
            header_rows.append(
                [_normalize_cell(cell.text_content()) for cell in tr.xpath(".//th | .//td")]
            )
        width = max(len(row) for row in header_rows)
        state_cols: list[int] = []
        premium_cols: list[int] = []
        for col in range(width):
            combined = " ".join(row[col] if col < len(row) else "" for row in header_rows).lower()
            if _contains_any(combined, _STATE_KEYWORDS) and not _contains_any(
                combined, _PREMIUM_KEYWORDS
            ):
                state_cols.append(col)
            if _contains_any(combined, _PREMIUM_KEYWORDS):
                premium_cols.append(col)
        # Pair each state column with the nearest premium column after it.
        pairs: list[tuple[int, int]] = []
        for state_col in state_cols:
            following = [p for p in premium_cols if p > state_col]
            if following:
                pairs.append((state_col, following[0]))
        if not pairs:
            continue
        rows: list[dict[str, Any]] = []
        for tr in row_elements[1:]:
            cells = [_normalize_cell(cell.text_content()) for cell in tr.xpath(".//th | .//td")]
            if len(cells) <= max(premium for _, premium in pairs):
                continue
            for state_col, premium_col in pairs:
                state = cells[state_col]
                premium = _as_money(cells[premium_col])
                if not state or not _looks_numeric(cells[premium_col]) or premium is None:
                    continue
                if state.lower() in _SKIP_STATES or state.lower() in _SKIP_STATE_HEADERS:
                    continue
                rows.append(
                    {
                        "state": state,
                        "premium": premium,
                        "source": "public_rate_table",
                        "url": page_url,
                    }
                )
        if rows:
            return rows
    return []
