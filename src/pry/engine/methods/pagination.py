"""Rate-limit-aware paginated crawl tier — fetch JSON list endpoints page by page."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from pry.engine.methods import _common

if TYPE_CHECKING:
    import httpx

_JSON_LIST_KEYS = ("results", "data", "items")


def _json_list_items(response: httpx.Response) -> list[dict[str, Any]]:
    """Extract a JSON list (or a list under ``results``/``data``/``items``)."""
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in _JSON_LIST_KEYS:
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def paginated_fetch(
    url: str,
    page_param: str = "page",
    max_pages: int = 5,
    per_page_delay: float = 0.5,
) -> list[dict[str, Any]]:
    """Fetch a JSON list endpoint across pages until empty.

    GETs ``url`` with ``page_param`` set to 1, 2, … up to ``max_pages``,
    sleeping ``per_page_delay`` seconds between requests (rate-limit
    courtesy), and stops early when a page returns no items. Pages are
    expected to be JSON lists; dict payloads are also unwrapped from the
    common ``results`` / ``data`` / ``items`` keys.

    Args:
        url: Absolute http(s) URL of the JSON list endpoint.
        page_param: Query-string parameter name for the page number.
        max_pages: Hard cap on the number of pages fetched.
        per_page_delay: Seconds to sleep between page requests.

    Returns:
        The concatenated items across pages, or ``[]`` on any failure.
        Never raises.
    """
    if not isinstance(url, str) or not url.strip():
        return []
    page_count = max(int(max_pages), 1)
    collected: list[dict[str, Any]] = []
    for page in range(1, page_count + 1):
        response = _common._sync_get(url, params={page_param: page})
        if response is None:
            break
        items = _json_list_items(response)
        if not items:
            break
        collected.extend(items)
        if page < page_count and per_page_delay > 0:
            time.sleep(per_page_delay)
    return collected


__all__ = ["paginated_fetch"]
