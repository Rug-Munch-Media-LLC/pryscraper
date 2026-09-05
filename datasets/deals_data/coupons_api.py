"""Public API for deal-aggregator coupon scraping.

Orchestrates fetching + parsing across Slickdeals and RetailMeNot and
aggregates the results into the canonical deal record shape.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
from typing import Any

from datasets.deals_data.coupons_common import (
    _BLOCKED,
    _LOCK,
    _RETAILMENOT_SEARCH_URL,
    _RETAILMENOT_STORE_URL,
    _SLICKDEALS_SEARCH_URL,
    _SLICKDEALS_STORE_URL,
    _clamp_limit,
    _dedupe_deals,
    _fetch,
    _is_blocked_html,
    _mark_blocked,
    _url_quote,
)
from datasets.deals_data.coupons_parsing import (
    _parse_retailmenot_html,
    _parse_slickdeals_html,
    _parse_structured_deals,
)

logger = logging.getLogger(__name__)


async def search_deals(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search Slickdeals + RetailMeNot for deals matching ``query``.

    Best-effort: both aggregators are anti-bot / JS-heavy, so results may
    legitimately be ``[]`` (check :func:`blocked_sources` to tell a block
    apart from a genuinely empty result set). Dedupes by url and caps at
    ``limit``. Async, never raises.
    """
    text = (query or "").strip()
    bounded = _clamp_limit(limit)
    with _LOCK:
        _BLOCKED.clear()
    if not text:
        return []
    out: list[dict[str, Any]] = []
    # Slickdeals search page (classic results + structured data).
    raw = await _fetch(_SLICKDEALS_SEARCH_URL, params={"q": text, "searcharea": "deals"})
    if raw:
        if _is_blocked_html(raw):
            logger.warning("deals_antibot_blocked", extra={"source": "slickdeals"})
            _mark_blocked("slickdeals", True)
        else:
            out.extend(_parse_structured_deals("slickdeals", raw))
            out.extend(_parse_slickdeals_html(raw))
    # RetailMeNot search page (coupon cards + structured data).
    raw = await _fetch(_RETAILMENOT_SEARCH_URL.format(q=_url_quote(text)))
    if raw:
        if _is_blocked_html(raw):
            logger.warning("deals_antibot_blocked", extra={"source": "retailmenot"})
            _mark_blocked("retailmenot", True)
        else:
            out.extend(_parse_structured_deals("retailmenot", raw))
            out.extend(_parse_retailmenot_html(raw))
    return _dedupe_deals(out, bounded)


async def get_store_deals(store: str, limit: int = 20) -> list[dict[str, Any]]:
    """Fetch deals/coupons for one retailer from Slickdeals + RetailMeNot.

    ``store`` may be a bare name (``"amazon"``) — both aggregators accept
    slugs. Same honest-degradation contract as :func:`search_deals`.
    Async, never raises.
    """
    slug = (store or "").strip().lower()
    bounded = _clamp_limit(limit)
    with _LOCK:
        _BLOCKED.clear()
    if not slug:
        return []
    out: list[dict[str, Any]] = []
    # Slickdeals store landing page.
    raw = await _fetch(_SLICKDEALS_STORE_URL.format(store=_url_quote(slug)))
    if raw:
        if _is_blocked_html(raw):
            logger.warning("deals_antibot_blocked", extra={"source": "slickdeals"})
            _mark_blocked("slickdeals", True)
        else:
            out.extend(_parse_structured_deals("slickdeals", raw))
            out.extend(_parse_slickdeals_html(raw))
    # RetailMeNot store landing page (/view/{store}).
    raw = await _fetch(_RETAILMENOT_STORE_URL.format(store=_url_quote(slug)))
    if raw:
        if _is_blocked_html(raw):
            logger.warning("deals_antibot_blocked", extra={"source": "retailmenot"})
            _mark_blocked("retailmenot", True)
        else:
            out.extend(_parse_structured_deals("retailmenot", raw))
            out.extend(_parse_retailmenot_html(raw))
    return _dedupe_deals(out, bounded)
