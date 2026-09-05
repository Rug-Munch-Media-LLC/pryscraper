"""CoinMarketCap new-listings page scrape (best-effort secondary source).

``coinmarketcap.com/new/`` is a Next.js page: we extract the embedded
``__NEXT_DATA__`` JSON (no browser). CMC may block datacenter traffic, so
any failure degrades to an empty list.
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

from crypto_market._http import _get_text
from crypto_market._normalize import (
    _created_epoch,
    _entry_age_minutes,
    _f,
    _normalize_iso_utc,
)
from crypto_market._registry import CMC_PLATFORM_ALIASES

CMC_NEW_URL = "https://coinmarketcap.com/new/"

_NEXT_DATA_RE = re.compile(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)


def _extract_next_data(html_text: str) -> dict[str, Any] | None:
    """Pull and parse the ``__NEXT_DATA__`` JSON blob from a Next.js page."""
    match = _NEXT_DATA_RE.search(html_text or "")
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _cmc_chain_from_platform(platform: Any) -> str:
    """Map a CoinMarketCap platform id/name to a supported chain ("" unknown)."""
    platform_id = ""
    if isinstance(platform, dict):
        platform_id = str(platform.get("id") or platform.get("name") or "")
    elif platform is not None:
        platform_id = str(platform)
    pid = platform_id.strip().lower()
    return CMC_PLATFORM_ALIASES.get(pid, "")


def _extract_cmc_coin_rows(node: Any, out: list[dict[str, Any]]) -> None:
    """Recursively collect CoinMarketCap coin-row dicts from the page state.

    CMC's new-listings page stores rows under ``props.initialState...data``
    with per-coin ``quote.USD``; walk the whole embedded JSON for dicts that
    look like coin rows (have ``symbol`` + ``quote.USD``).
    """
    if isinstance(node, list):
        for child in node:
            _extract_cmc_coin_rows(child, out)
        return
    if not isinstance(node, dict):
        return
    quote = node.get("quote")
    if (
        isinstance(quote, dict)
        and isinstance(quote.get("USD"), dict)
        and str(node.get("symbol") or "").strip()
        and str(node.get("name") or "").strip()
    ):
        out.append(node)
    for value in node.values():
        _extract_cmc_coin_rows(value, out)


def _normalize_cmc_row(row: dict[str, Any], chain_filter: str | None) -> dict[str, Any] | None:
    """Normalize a CoinMarketCap coin row into the shared schema.

    ``chain`` is attributed from the platform field when possible; rows with
    an unknown chain are kept only when no chain filter is applied (their
    ``chain`` is left empty per the schema).
    """
    quote = row.get("quote")
    usd = quote.get("USD") if isinstance(quote, dict) else None
    if not isinstance(usd, dict):
        return None
    symbol = str(row.get("symbol") or "")
    name = str(row.get("name") or "")
    if not symbol and not name:
        return None
    chain = _cmc_chain_from_platform(row.get("platform"))
    if chain_filter is not None and chain != chain_filter:
        return None
    return {
        "chain": chain,
        "address": str(row.get("tokenAddress") or row.get("slug") or ""),
        "symbol": symbol,
        "name": name,
        "pair_address": "",
        "created_at_utc": _normalize_iso_utc(row.get("date_added") or row.get("last_updated")),
        "price_usd": _f(usd.get("price")),
        "liquidity_usd": 0.0,  # not exposed by the CMC scrape
        "volume_24h_usd": _f(usd.get("volume_24h")),
        "price_change_24h_pct": _f(usd.get("percent_change_24h")),
        "source": "coinmarketcap",
    }


async def _new_tokens_cmc(
    chain: str | None, limit: int, min_age_minutes: int
) -> list[dict[str, Any]]:
    """CoinMarketCap new-listings page scrape (best-effort, no key)."""
    page = await _get_text(CMC_NEW_URL)
    if not page:
        return []
    payload = _extract_next_data(page)
    if payload is None:
        return []
    rows: list[dict[str, Any]] = []
    _extract_cmc_coin_rows(payload, rows)
    if not rows:
        return []
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    for row in rows:
        normalized = _normalize_cmc_row(row, chain)
        if normalized is None:
            continue
        dedupe_key = f"{normalized['symbol']}:{normalized['name']}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        if min_age_minutes > 0:
            age = _entry_age_minutes(normalized)
            if age is None or age < min_age_minutes:
                continue
        results.append(normalized)
    results.sort(key=_created_epoch, reverse=True)
    return results[:limit] if limit else results


__all__ = [
    "_cmc_chain_from_platform",
    "_extract_cmc_coin_rows",
    "_extract_next_data",
    "_new_tokens_cmc",
    "_normalize_cmc_row",
]
