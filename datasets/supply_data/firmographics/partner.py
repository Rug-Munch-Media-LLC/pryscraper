"""Optional partner API enrichment for headcount and funding."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from datasets.supply_data.firmographics.http import (
    _HEADERS,
    _RETRY_CONFIG,
    _TIMEOUT,
)
from datasets.supply_data.firmographics.normalization import _as_money
from pry.engine.retry import async_retry

logger = logging.getLogger(__name__)
_FIRMO_API_URL = os.environ.get("PRY_FIRMO_API_URL", "https://firmo.example.com/v1/companies")
_FIRMO_API_KEY_ENV = "PRY_FIRMO_API_KEY"


def _as_int_any(value: Any) -> int | None:
    """Coerce a JSON value to ``int`` or ``None``."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    digits = text[1:] if text[:1] in {"+", "-"} else text
    return int(text) if digits.isdecimal() else None


async def _partner_firmographics(company: str) -> dict[str, Any]:
    """Fetch optional partner headcount and funding fields."""
    empty = {"headcount": None, "funding": None, "total_funding": None}
    key = os.environ.get(_FIRMO_API_KEY_ENV, "").strip()
    if not key:
        logger.warning(
            "firmographics_partner_not_configured",
            extra={
                "company": company,
                "hint": "set PRY_FIRMO_API_URL + PRY_FIRMO_API_KEY for funding/headcount",
            },
        )
        return empty
    api_url = os.environ.get("PRY_FIRMO_API_URL", "").strip() or _FIRMO_API_URL

    async def _one() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
            response = await client.get(api_url, params={"api_key": key, "company": company})
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("partner firmographics payload is not an object")
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        if not isinstance(data, dict):
            raise ValueError("partner firmographics missing data object")
        return {
            "headcount": _as_int_any(data.get("headcount") or data.get("num_employees")),
            "funding": _as_money(data.get("funding") or data.get("last_funding")),
            "total_funding": _as_money(
                data.get("total_funding") or data.get("totalFunding") or data.get("raised")
            ),
        }

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        logger.debug("firmographics_partner_fetch_failed", exc_info=True)
        return empty
