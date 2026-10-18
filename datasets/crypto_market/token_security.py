"""Dataset facade — token security scans (rug / honeypot risk).

The GoPlus-backed scanner and its heuristic fallback live in the canonical
:mod:`crypto_market` package. This module is the stable
``datasets.crypto_market`` import path used by the HTTP router and adds
structured logging at the dataset boundary.

``scan_token`` always returns a dict (``risk_score``, ``risk_level``,
``findings``, ...) and never raises, including when GoPlus is unreachable.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
from typing import Any

from crypto_market.token_security import scan_token as _scan_token

logger = logging.getLogger(__name__)


async def scan_token(chain: str, address: str) -> dict[str, Any]:
    """Scan a token for rug-pull risk; returns a verdict dict, never raises."""
    result = await _scan_token(chain, address)
    # The MCP output schema names the verdict ``risk_level``; expose it as an
    # additive alias of the canonical ``verdict`` (no invented severity).
    if "risk_level" not in result:
        result = {**result, "risk_level": result.get("verdict", "unknown")}
    logger.info(
        "crypto_market_dataset_token_security",
        extra={
            "chain": chain,
            "address": address,
            "risk_level": result["risk_level"],
            "source": result.get("source", "none"),
        },
    )
    return result


__all__ = ["scan_token"]
