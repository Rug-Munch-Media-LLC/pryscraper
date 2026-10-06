"""Embedded-JSON extraction for retail marketplace pages.
Extracts JSON-LD ``Product`` / ``ItemList`` objects and the Next.js
``__NEXT_DATA__`` state / ``window.__INITIAL_STATE__`` /
``__PRELOADED_STATE__`` / ``__APOLLO_STATE__`` redux blobs.
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pry.commerce.marketplace import _find_script_json

logger = logging.getLogger(__name__)

_WINDOW_STATE_MARKERS = (
    "__NEXT_DATA__",
    "__INITIAL_STATE__",
    "__PRELOADED_STATE__",
    "__APOLLO_STATE__",
)
_LD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


def _extract_window_state(html_text: str, marker: str) -> Any:
    """Parse ``window.<marker> = {...};`` JSON via brace counting; None on failure."""
    if not html_text:
        return None
    idx = html_text.find(f"window.{marker}")
    if idx < 0:
        return None
    start = html_text.find("{", idx)
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(html_text)):
        ch = html_text[i]
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
                    data = json.loads(html_text[start : i + 1])
                    return data if isinstance(data, dict) else None
                except json.JSONDecodeError:
                    logger.warning("retail_extract_suppressed", exc_info=True)
                    return None
    return None


def _embedded_state(html_text: str) -> Any:
    """Return the first parseable embedded state blob (dict) or None."""
    state = _find_script_json(html_text, "__NEXT_DATA__")
    if state is not None:
        return state
    for marker in _WINDOW_STATE_MARKERS:
        state = _extract_window_state(html_text, marker)
        if state is not None:
            return state
    return None


def _json_ld_objects(html_text: str) -> list[Any]:
    """Every JSON-LD object embedded in the page (never raises)."""
    out: list[Any] = []
    for match in _LD_RE.finditer(html_text or ""):
        try:
            data = json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            logger.warning("retail_extract_suppressed", exc_info=True)
            continue
        if isinstance(data, list):
            out.extend(data)
        elif isinstance(data, dict):
            out.append(data)
    return out


def _ld_type(obj: Any) -> str:
    if isinstance(obj, dict):
        value = obj.get("@type")
        if isinstance(value, list):
            return " ".join(str(item) for item in value)
        return str(value or "")
    return ""


def _find_ld_product(html_text: str) -> dict[str, Any] | None:
    for obj in _json_ld_objects(html_text):
        if "Product" in _ld_type(obj):
            return obj if isinstance(obj, dict) else None
    return None


def _find_ld_search_items(html_text: str) -> list[dict[str, Any]]:
    """JSON-LD search candidates: ItemList entries and bare Product objects."""
    items: list[dict[str, Any]] = []
    for obj in _json_ld_objects(html_text):
        obj_type = _ld_type(obj)
        if "ItemList" in obj_type:
            elements = obj.get("itemListElement")
            if isinstance(elements, list):
                for element in elements:
                    if not isinstance(element, dict):
                        continue
                    item = element.get("item")
                    if isinstance(item, dict):
                        items.append(item)
                    else:
                        items.append(element)
        elif "Product" in obj_type and isinstance(obj, dict):
            items.append(obj)
    return items
