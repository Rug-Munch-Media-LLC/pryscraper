"""Amazon Rainforest fallback — free tier, env key only.

Consulted only when direct Amazon scraping fails; the key is read from
the environment at call time (never hardcoded).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import os
from typing import Any

from pry.commerce.marketplace.http import _fetch_json


def _rainforest_api_key() -> str:
    """Rainforest free-tier key from the environment; "" when unset."""
    for name in ("PRY_RAINFOREST_API_KEY", "RAINFOREST_API_KEY"):
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


async def _amazon_via_rainforest(url: str) -> Any:
    """Best-effort Rainforest request; returns parsed JSON or None (never raises)."""
    key = _rainforest_api_key()
    if not key:
        return None
    return await _fetch_json(
        "https://api.rainforestapi.com/request",
        params={"api_key": key, "type": "product", "url": url},
    )
