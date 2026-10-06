"""Pry — earnings computation helpers.

Shared helpers and tier lookup used by the earnings computation mixins.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


def _ensure_aware(dt: datetime) -> datetime:
    """Normalize a parsed datetime to timezone-aware UTC (naive == UTC)."""
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        k = str(item.get(key, "unknown"))
        counts[k] = counts.get(k, 0) + 1
    return counts


#: Safe tier price lookup (name -> {"price_usd_monthly": float | None}).
def _tiers_safe() -> dict[str, dict[str, Any]]:
    try:
        from pry.commerce.billing.tiers import TIERS

        return {name: {"price_usd_monthly": tier.price_usd_monthly} for name, tier in TIERS.items()}
    except (ImportError, AttributeError) as exc:  # pragma: no cover
        logger.warning(
            "payments_exception_swallowed",
            extra={"error": str(exc), "handler": "_tiers_safe"},
        )
        return {}


TIERS_SAFE: dict[str, dict[str, Any]] = _tiers_safe()
