"""HTTP fetchers + quote probing + public API for insurance data.

Split out of ``insurance.py`` (god-file reduction). The ``insurance.py``
facade re-exports everything here so the surface is unchanged.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from datasets.healthcare_data.insurance_common import (
    _BROWSER_HEADERS,
    _COVERAGE_TYPES,
    _PROBE_RETRY,
    _PROBE_TIMEOUT,
    _PROVIDERS,
    _RATE_PAGES,
    _RETRY_CONFIG,
    _TIMEOUT,
    _is_gated,
    _match_state,
    _NotScrapeable,
    _parse_quote_page,
)
from datasets.healthcare_data.insurance_parsers import _parse_rate_table
from pry.engine.retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)


# ── quote probing ──────────────────────────────────────────────────────
async def _probe_provider(name: str, url: str, zipcode: str | None) -> dict[str, Any] | None:
    """Fetch one quote form; None when gated or without parseable data."""

    async def _one() -> dict[str, Any]:
        params = {"zipcode": zipcode} if zipcode else None
        async with httpx.AsyncClient(
            timeout=_PROBE_TIMEOUT, headers=_BROWSER_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url, params=params)
            status = response.status_code
            ctype = response.headers.get("content-type", "")
            body = response.text[:20000]
        if _is_gated(status, ctype, body.lower()):
            raise _NotScrapeable(name)
        premium = _parse_quote_page(body)
        if premium is None:
            raise _NotScrapeable(name)
        return {"provider": name, "premium": premium, "deductible": None, "url": url}

    try:
        return await async_retry(_one, config=_PROBE_RETRY)
    except (_NotScrapeable, httpx.HTTPError, OSError, ValueError):
        return None


# ── public rate tables ─────────────────────────────────────────────────
async def _fetch_html(url: str, request_timeout: httpx.Timeout, config: RetryConfig) -> str | None:
    async def _one() -> str:
        async with httpx.AsyncClient(
            timeout=request_timeout, headers=_BROWSER_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text

    try:
        return await async_retry(_one, config=config)
    except (httpx.HTTPError, OSError) as exc:
        logger.warning("insurance_fetch_failed", extra={"error": str(exc)[:120]})
        return None


# ── Public API ─────────────────────────────────────────────────────────
async def get_insurance_quotes(profile: dict[str, Any]) -> dict[str, Any]:
    """Request car/home insurance quotes.

    Args:
        profile: dict with ``coverage_type`` (``"auto"`` (default) |
            ``"home"``) and optional ``zip``.

    Returns:
        ``{"available": True, "coverage_type": ..., "quotes":
        [{provider, premium, deductible, url}]}`` when a provider page is
        parseable, otherwise the documented ``{"available": False,
        "reason": ..., "quotes": []}`` payload. Never raises and never
        returns fabricated premiums.
    """
    try:
        return await _get_insurance_quotes(profile)
    except Exception:
        logger.exception("health_insurance_quotes_crashed")
        return {
            "available": False,
            "reason": "insurance quote lookup failed unexpectedly",
            "coverage_type": str((profile or {}).get("coverage_type") or "auto"),
            "quotes": [],
        }


async def _get_insurance_quotes(profile: dict[str, Any]) -> dict[str, Any]:
    profile = profile or {}
    coverage_type = str(profile.get("coverage_type") or "auto").strip().lower()
    if coverage_type not in _COVERAGE_TYPES:
        return {
            "available": False,
            "reason": (
                f"unsupported coverage_type {coverage_type!r}; "
                f"expected one of {sorted(_COVERAGE_TYPES)}"
            ),
            "coverage_type": coverage_type,
            "quotes": [],
        }
    zipcode = str(profile.get("zip") or "").strip() or None
    providers = _PROVIDERS.get(coverage_type, ())
    results = await asyncio.gather(
        *(_probe_provider(name, url, zipcode) for name, url in providers)
    )
    quotes = [result for result in results if result is not None]
    sources_checked = [name for name, _ in providers]
    if quotes:
        return {
            "available": True,
            "coverage_type": coverage_type,
            "quotes": quotes,
            "sources_checked": sources_checked,
        }
    return {
        "available": False,
        "coverage_type": coverage_type,
        "quotes": [],
        "sources_checked": sources_checked,
        "reason": (
            "Car/home insurance quote forms are captcha/JS-gated and cannot be "
            "scraped reliably without a paid quote API or browser automation. "
            "Use get_insurance_rate_table() for public aggregate rate-table data."
        ),
    }


async def get_insurance_rate_table(
    state: str | None = None, coverage_type: str = "auto"
) -> list[dict[str, Any]]:
    """Fetch public aggregate insurance rate-table data.

    Args:
        state: Optional US state name or two-letter abbreviation (e.g.
            ``"CA"``, ``"Texas"``) to filter rows; None returns all states.
        coverage_type: ``"auto"`` (default) or ``"home"``.

    Returns:
        A list of ``{state, premium, source, url}`` records. ``[]`` on
        failure or unsupported coverage_type. Never raises.
    """
    try:
        return await _get_insurance_rate_table(state, coverage_type)
    except Exception:
        logger.exception(
            "health_insurance_rate_table_crashed",
            extra={"state": state, "coverage_type": coverage_type},
        )
        return []


async def _get_insurance_rate_table(state: str | None, coverage_type: str) -> list[dict[str, Any]]:
    normalized_type = str(coverage_type or "auto").strip().lower()
    page_url = _RATE_PAGES.get(normalized_type)
    if page_url is None:
        return []
    html = await _fetch_html(page_url, _TIMEOUT, _RETRY_CONFIG)
    if html is None:
        return []
    rows = _parse_rate_table(html, page_url)
    query = str(state or "").strip()
    if query:
        rows = [row for row in rows if _match_state(str(row.get("state") or ""), query)]
    return rows
