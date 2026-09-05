"""Value coercion / normalization helpers shared by crypto_market providers.

Every provider response is coerced into the shared normalized-entry
schema; these helpers do the timestamp, float, chain-argument, and
API-key plumbing. Pure functions — no I/O.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from typing import Any


def _normalize_chain_arg(chain: str | None) -> str | None:
    """Normalize the ``chain`` argument; None/""/"all" mean no filtering."""
    if chain is None:
        return None
    normalized = str(chain).strip().lower()
    if normalized in ("", "all"):
        return None
    return normalized


def _epoch_ms(value: Any) -> float | None:
    """Coerce a timestamp to epoch milliseconds.

    Handles both millisecond (DexScreener ``pairCreatedAt``) and second
    (CoinGecko ``activated_at``) inputs.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number if number > 1e12 else number * 1000.0


def _iso(value: Any) -> str:
    """ISO-8601 UTC string from an epoch timestamp (ms or s); "" on failure."""
    ms = _epoch_ms(value)
    if ms is None:
        return ""
    try:
        return datetime.fromtimestamp(ms / 1000.0, tz=UTC).isoformat()
    except (ValueError, OverflowError, OSError):
        return ""


def _f(value: Any, default: float = 0.0) -> float:
    """Coerce a numeric value to float; ``default`` on any failure."""
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _created_epoch(entry: dict[str, Any]) -> float:
    """Wall-clock epoch seconds of a normalized entry; -1 when unknown."""
    raw = entry.get("created_at_utc")
    if not raw:
        return -1.0
    try:
        return datetime.fromisoformat(str(raw)).timestamp()
    except (ValueError, TypeError, OSError):
        return -1.0


def _entry_age_minutes(entry: dict[str, Any]) -> float | None:
    """Age of an entry in minutes; None when creation time is unknown."""
    epoch = _created_epoch(entry)
    if epoch <= 0:
        return None
    return max(0.0, (time.time() - epoch) / 60.0)


def _normalize_iso_utc(value: Any) -> str:
    """Normalize an ISO-8601 string to ISO-8601 UTC ("" on failure)."""
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return ""
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def _api_key(*names: str) -> str:
    """Read an optional API key from the environment (never hardcoded)."""
    for name in names:
        value = os.getenv(name, "")
        if value:
            return value
    return ""


def _extract_pairs(data: Any) -> list[dict[str, Any]]:
    """Extract a pair list from a DexScreener response.

    Handles both shapes the API returns: ``{"pairs": [...]}`` and a bare
    list, plus null pairs (search returns ``pairs: null`` on no results).
    """
    if isinstance(data, dict):
        pairs = data.get("pairs")
        if isinstance(pairs, list):
            return [p for p in pairs if isinstance(p, dict)]
        return []
    if isinstance(data, list):
        return [p for p in data if isinstance(p, dict)]
    return []


__all__ = [
    "_api_key",
    "_created_epoch",
    "_entry_age_minutes",
    "_epoch_ms",
    "_extract_pairs",
    "_f",
    "_iso",
    "_normalize_chain_arg",
    "_normalize_iso_utc",
]
