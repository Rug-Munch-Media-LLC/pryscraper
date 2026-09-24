"""Cached ticker-to-CIK resolution for SEC EDGAR."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import time
from typing import Any

from datasets.legal_docs.sec_filings.identifiers import _as_text, _cik_to_padded
from datasets.legal_docs.sec_filings.transport import _fetch_json

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_TICKERS_CACHE_TTL = 12 * 60 * 60
_TICKERS_CACHE: dict[str, Any] | None = None
_TICKERS_CACHE_TS = 0.0


async def _tickers_index() -> dict[str, dict[str, Any]] | None:
    """Load and cache the SEC company-ticker index."""
    global _TICKERS_CACHE, _TICKERS_CACHE_TS
    now = time.monotonic()
    if _TICKERS_CACHE is not None and (now - _TICKERS_CACHE_TS) < _TICKERS_CACHE_TTL:
        return _TICKERS_CACHE
    payload = await _fetch_json(_TICKERS_URL)
    if not isinstance(payload, dict):
        return _TICKERS_CACHE
    index: dict[str, dict[str, Any]] = {}
    for raw in payload.values():
        if not isinstance(raw, dict):
            continue
        ticker = _as_text(raw.get("ticker"))
        if not ticker:
            continue
        index[ticker.upper()] = {
            "cik": _cik_to_padded(raw.get("cik_str")),
            "ticker": ticker,
            "title": _as_text(raw.get("title")),
        }
    if index:
        _TICKERS_CACHE = index
        _TICKERS_CACHE_TS = now
    return index


async def _cik_for_ticker(ticker: str) -> str | None:
    """Resolve a ticker to its zero-padded ten-digit CIK."""
    index = await _tickers_index()
    if not index:
        return None
    entry = index.get(ticker.strip().upper())
    return entry.get("cik") if entry else None


def reset_ticker_cache() -> None:
    """Drop the cached ticker index so the next lookup refetches it."""
    global _TICKERS_CACHE, _TICKERS_CACHE_TS
    _TICKERS_CACHE = None
    _TICKERS_CACHE_TS = 0.0
