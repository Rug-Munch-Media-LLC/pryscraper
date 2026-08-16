"""Company import records — ImportYeti/Panjiva-style bill-of-lading data.

The US Census / customs shipment data that powers ImportYeti and Panjiva is
behind login walls and paid subscriptions, and ImportYeti's free web UI is
Cloudflare anti-bot protected. There is no anonymous, no-auth, company-level
import-record API. This module therefore talks to a partner API that exposes
Panjiva-style records when a key is configured, and otherwise degrades to
``[]`` with an honest ``imports_source_login_wall`` log.

Source configuration (both optional, env-driven — never in code):
* ``PRY_IMPORTS_API_URL`` — base URL of the partner import-records API
  (defaults to a documented placeholder; override in production).
* ``PRY_IMPORTS_API_KEY`` — partner key sent as ``api_key`` query param.
  Without a key every function returns ``[]`` (never raises).

Contract
--------
* :func:`get_import_records` — async, never raises, returns a ``list``
  (``[]`` on failure or when the source is not configured).

Result shape
------------
``get_import_records`` returns a list of:

    {
        "company": "Acme Trading Co",
        "hs_code": "8471.30",
        "product": "Laptop computers",
        "origin": "CN",
        "consignee": "Acme Trading Co",
        "shipment_date": "2026-06-14",
        "quantity": 4200,
        "teu": 6,
        "source": "imports_partner",
    }

Degradation
-----------
* No API key configured → ``[]`` + ``imports_source_login_wall`` log
  (ImportYeti/Panjiva free tiers sit behind login/anti-bot walls).
* Partner responds with an anti-bot / login-required marker → ``[]`` +
  ``imports_source_anti_bot`` log.
* Network error / non-2xx / malformed payload → ``[]``.
* Records missing optional fields are kept as *partial* records with
  ``None`` in the missing slots (the lead-gen value survives).

Free-API terms: this module does not scrape ImportYeti/Panjiva. It only
calls the partner endpoint you configure. Backoff: 2 retries, exponential
(0.4s -> 1.6s).

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
import os
from typing import Any

import httpx

from retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

_IMPORTS_API_URL = os.environ.get("PRY_IMPORTS_API_URL", "https://imports.example.com/v1/records")
_API_KEY_ENV = "PRY_IMPORTS_API_KEY"
_TIMEOUT = httpx.Timeout(20.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.4,
    max_delay=1.6,
    retryable_exceptions=(httpx.HTTPError,),
)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; pryscraper-supply/1.0; "
        "+https://git.rugmunch.io/RugMunchMedia/pryscraper)"
    ),
    "Accept": "application/json",
}
_MAX_LIMIT = 200
# Keys a partner may return to signal an anti-bot / login wall instead of data.
_BLOCK_MARKERS = ("blocked", "login_required", "challenge_required", "forbidden")


def _api_key() -> str:
    """Return the configured partner API key, or '' when missing."""
    return os.environ.get(_API_KEY_ENV, "").strip()


def _as_text(value: Any) -> str | None:
    """Coerce a JSON value to str/None ('' -> None)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_int(value: Any) -> int | None:
    """Coerce a JSON value to int/None."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _map_record(raw: dict[str, Any], company: str) -> dict[str, Any]:
    """Map a partner record onto the canonical import-record shape.

    Optional fields are filled with None when missing — the record is kept
    (partial degrade) instead of being dropped.
    """
    consignee = _as_text(raw.get("consignee")) or _as_text(raw.get("importer"))
    return {
        "company": _as_text(raw.get("company")) or company,
        "hs_code": _as_text(raw.get("hs_code")) or _as_text(raw.get("hsCode")),
        "product": _as_text(raw.get("product")) or _as_text(raw.get("product_description")),
        "origin": _as_text(raw.get("origin")) or _as_text(raw.get("origin_country")),
        "consignee": consignee,
        "shipment_date": _as_text(raw.get("shipment_date")) or _as_text(raw.get("arrival_date")),
        "quantity": _as_int(raw.get("quantity")) if raw.get("quantity") is not None else None,
        "teu": _as_int(raw.get("teu")) if raw.get("teu") is not None else None,
        "source": _as_text(raw.get("source")) or "imports_partner",
    }


def _records_from_payload(payload: Any) -> list[dict[str, Any]]:
    """Pull the record list out of a partner payload (multiple shapes)."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("records", "data", "results", "shipments"):
        value = payload.get(key)
        if isinstance(value, list):
            return [r for r in value if isinstance(r, dict)]
    return []


def _is_blocked(payload: Any) -> bool:
    """Return True when the partner payload signals a login/anti-bot wall."""
    if not isinstance(payload, dict):
        return False
    for key in _BLOCK_MARKERS:
        if bool(payload.get(key)):
            return True
        value = payload.get("meta")
        if isinstance(value, dict) and bool(value.get(key)):
            return True
    return False


async def _fetch_records(params: dict[str, str]) -> Any | None:
    """GET the partner import-records API and return the decoded payload.

    Returns ``None`` on any failure (network, non-2xx, malformed payload).
    """

    async def _one() -> Any:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            response = await client.get(_IMPORTS_API_URL, params=params)
            response.raise_for_status()
            return response.json()

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except (httpx.HTTPError, OSError, ValueError):
        return None


# ── Public API ─────────────────────────────────────────────────────────
async def get_import_records(company: str, limit: int = 20) -> list[dict[str, Any]]:
    """Return ImportYeti/Panjiva-style import records for a company.

    Args:
        company: Company name to look up (e.g. ``"Acme Trading Co"``).
        limit: Max records to return (1-200).

    Returns:
        A list of import-record dicts (see module docstring). ``[]`` on
        failure, when the company is blank, or when no partner API key is
        configured (the free sources sit behind login/anti-bot walls —
        logged as ``imports_source_login_wall``). Never raises.
    """
    try:
        return await _get_import_records(company, limit)
    except Exception:
        logger.exception("supply_imports_crashed", extra={"company": company})
        return []


async def _get_import_records(company: str, limit: int) -> list[dict[str, Any]]:
    company = company.strip()
    if not company:
        return []
    key = _api_key()
    if not key:
        # ImportYeti free search is Cloudflare anti-bot + login gated; Panjiva
        # is subscription-only. Honest flag instead of scraping them.
        logger.warning(
            "imports_source_login_wall",
            extra={
                "company": company,
                "hint": "set PRY_IMPORTS_API_KEY + PRY_IMPORTS_API_URL to a partner API",
            },
        )
        return []
    params: dict[str, str] = {
        "api_key": key,
        "company": company,
        "limit": str(max(1, min(int(limit), _MAX_LIMIT))),
    }
    payload = await _fetch_records(params)
    if payload is None:
        return []
    if _is_blocked(payload):
        logger.warning("imports_source_anti_bot", extra={"company": company})
        return []
    records = _records_from_payload(payload)
    return [_map_record(raw, company) for raw in records][: int(limit)]
