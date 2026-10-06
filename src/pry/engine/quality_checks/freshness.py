"""Freshness assessment for extracted data.

Split out of ``pry.engine.quality`` so the validation guard can live beside
the logic it guards, instead of growing a file the shrink-only ratchet
already watches.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
import math
import time
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


def compute_freshness(
    data: dict[str, Any] | list[Any], max_age_seconds: int = 3600
) -> dict[str, Any]:
    """Check data freshness against expected age.

    A non-dict ``data``, or an unusable ``max_age_seconds`` (``bool``, NaN,
    inf, negative — every one of which would mark arbitrarily stale data as
    fresh), returns a neutral default with a note rather than guessing or
    raising from ``data.get(...)``.
    """
    if not isinstance(data, dict):
        return {
            "fresh": True,
            "age_seconds": None,
            "note": "Data is not a dict — cannot verify freshness",
        }

    unusable = (
        isinstance(max_age_seconds, bool)
        or not isinstance(max_age_seconds, int | float)
        or not math.isfinite(max_age_seconds)
        or max_age_seconds < 0
    )
    if unusable:
        return {
            "fresh": True,
            "age_seconds": None,
            "note": "Invalid max age — cannot verify freshness",
        }

    now = time.time()
    timestamps = []

    # Look for timestamp fields
    for key in ["timestamp", "checked_at", "cached_at", "scraped_at", "created_at", "updated_at"]:
        val = data.get(key)
        if val:
            timestamps.append(val)

    if not timestamps:
        return {
            "fresh": True,
            "age_seconds": None,
            "note": "No timestamp field found in data — cannot verify freshness",
        }

    # Try to parse the first timestamp
    ts = timestamps[0]
    if isinstance(ts, (int, float)):
        age = now - ts
    elif isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts)
            age = now - dt.timestamp()
        except (ValueError, TypeError):
            logger.warning("silent_exception_swallowed", exc_info=True)
            return {
                "fresh": True,
                "age_seconds": None,
                "note": f"Could not parse timestamp: {ts[:30]}",
            }
    else:
        return {"fresh": True, "age_seconds": None, "note": "Timestamp in unknown format"}

    return {
        "fresh": age <= max_age_seconds,
        "age_seconds": round(age),
        "max_age_seconds": max_age_seconds,
        "note": f"Data is {_format_age(age)} old",
    }


def _format_age(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds / 60)}m"
    elif seconds < 86400:
        return f"{int(seconds / 3600)}h"
    return f"{int(seconds / 86400)}d"
