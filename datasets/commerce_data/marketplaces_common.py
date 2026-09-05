"""Shared pure helpers for the commerce marketplaces modules.

Extracted from :mod:`commerce_data.marketplaces` so each marketplace
adapter stays focused on its own source. Everything here is
side-effect-free parsing/coercion logic over JSON trees, HTML snippets
and XML elements — no network I/O.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import html
import json
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

if TYPE_CHECKING:
    import xml.etree.ElementTree as ET
    from collections.abc import Iterator

MARKETPLACES = ("ebay", "etsy", "aliexpress", "shopify", "target", "bestbuy")

# Retailers routed through marketplace.retail (JSON-LD / embedded state).
_RETAIL_MARKETPLACES = ("target", "bestbuy")

_MAX_LIMIT = 250  # Shopify products.json caps at 250 per page

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.DOTALL
)
_META_PROP_RE = re.compile(r'<meta[^>]+property="([^"]*)"[^>]*content="([^"]*)"', re.DOTALL)


def _clamp_limit(limit: Any) -> int:
    """Coerce ``limit`` to an int within [1, _MAX_LIMIT]; default 20."""
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = 20
    return max(1, min(value, _MAX_LIMIT))


def _url_quote(query: str) -> str:
    return quote(query, safe="")


def _to_float(value: Any) -> float | None:
    """Coerce a JSON/text value to float; None when not numeric."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _parse_money(text: str | None) -> float | None:
    """Extract a price number from a money string like 'US $1,234.56'."""
    if not text:
        return None
    match = re.search(r"\d[\d.,]*", text)
    if not match:
        return None
    digits = match.group(0).replace(",", "")
    try:
        return float(digits)
    except ValueError:
        return None


def _walk_dicts(obj: Any) -> Iterator[dict[str, Any]]:
    """Yield every dict (at any depth) inside a parsed JSON tree."""
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk_dicts(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk_dicts(value)


def _deep_first(obj: Any, keys: tuple[str, ...]) -> Any:
    """First non-None value found for any of ``keys`` at any depth."""
    for d in _walk_dicts(obj):
        for key in keys:
            value = d.get(key)
            if value is not None:
                return value
    return None


def _price_from(obj: Any, keys: tuple[str, ...]) -> float | None:
    """Best-effort price extraction (plain numbers, money strings, or
    ``{"amount": .., "divisor": .., "currency_code": ..}`` dicts)."""
    for d in _walk_dicts(obj):
        for key in keys:
            value = d.get(key)
            if value is None:
                continue
            if isinstance(value, dict):
                amount = value.get("amount")
                divisor = value.get("divisor")
                if (
                    isinstance(amount, (int, float))
                    and isinstance(divisor, (int, float))
                    and divisor
                ):
                    return float(amount) / float(divisor)
                continue
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                parsed = _parse_money(value)
                if parsed is not None:
                    return parsed
    return None


def _extract_next_data(raw: str) -> Any:
    """Parse the Next.js ``__NEXT_DATA__`` JSON blob (Etsy search pages)."""
    match = _NEXT_DATA_RE.search(raw)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def _extract_script_object(raw: str, marker: str) -> Any:
    """Parse the first JSON object assigned after ``marker`` (string-aware)."""
    idx = raw.find(marker)
    if idx < 0:
        return None
    start = raw.find("{", idx)
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(raw)):
        ch = raw[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _meta_content(raw: str, prop: str) -> str | None:
    """Return the ``content`` of the first ``<meta property="...">`` tag."""
    for p, content in _META_PROP_RE.findall(raw):
        if p == prop and content.strip():
            return html.unescape(content.strip())
    return None


def _elem_text(element: ET.Element, path: str, namespaces: dict[str, str]) -> str | None:
    found = element.find(path, namespaces)
    if found is None or found.text is None:
        return None
    text = found.text.strip()
    return text or None
