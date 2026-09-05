"""Shared constants + helpers for the government contract collectors.

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

import httpx

from pry.engine.retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(20.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.4,
    max_delay=1.6,
    retryable_exceptions=(httpx.HTTPError,),
)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; pryscraper-bidding/1.0; "
        "+https://git.rugmunch.io/RugMunchMedia/pryscraper)"
    ),
    "Accept": "application/json",
}

# SAM.gov free API key: https://sam.gov/content/webservices
_API_KEY_ENV = "PRY_SAM_API_KEY"
_SAM_BASE = "https://api.sam.gov/opportunities/v2/search"
_SAM_MAX_LIMIT = 200

_TED_BASE = "https://api.ted.europa.eu/v3/notices/search"
_TED_DETAIL_BASE = "https://api.ted.europa.eu/v3/notices"

_NY_BASE = "https://www.nycr.ny.gov/api/contracts/search"
_NY_DETAIL_BASE = "https://www.nycr.ny.gov/api/contracts"

_FEDCONNECT_BASE = "https://www.fedconnect.net/FedConnect/PublicPages/PublicSearch.aspx"

# Module-level reference to gov_data.procurement, resolved lazily so the
# package works even while sibling gov_data modules are still landing.
_gov_data_procurement: Any | None = None


# ── Shared helpers ──────────────────────────────────────────────────────
def _as_text(value: Any) -> str | None:
    """Coerce a JSON value to str/None ('' -> None)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _canonical_type(notice_type: str | None) -> str:
    """Map a raw notice type to the canonical ``solicitation``/``award``."""
    if not notice_type:
        return "solicitation"
    lowered = notice_type.lower()
    return "award" if "award" in lowered else "solicitation"


def _sort_by_due_date(records: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Sort merged records by due date ascending (soonest first, None last)."""
    records.sort(key=lambda r: (r.get("due_date") is None, str(r.get("due_date") or "")))
    return records[:limit]


async def _fetch_json(url: str, params: dict[str, str] | None = None) -> dict[str, Any] | None:
    """GET ``url`` and return the parsed JSON object, or ``None`` on failure."""

    async def _one() -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("bidding payload is not an object")
        return payload

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


async def _fetch_text(url: str, params: dict[str, str] | None = None) -> str | None:
    """GET ``url`` and return the raw response text, or ``None`` on failure."""

    async def _one() -> str:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
        return response.text

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError):
        return None


def _gov_procurement() -> Any | None:
    """Return the ``gov_data.procurement`` module, or ``None`` when absent.

    The reference is cached on first resolution so callers (and tests) can
    force the direct SAM.gov path by clearing ``_gov_data_procurement``.
    """
    global _gov_data_procurement
    if _gov_data_procurement is None:
        try:
            import gov_data.procurement as _module  # type: ignore[attr-defined]

            _gov_data_procurement = _module
        except ImportError:  # pragma: no cover — parallel build not landed yet
            _gov_data_procurement = None
    return _gov_data_procurement
