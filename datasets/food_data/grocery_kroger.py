"""Kroger API source — OAuth2 client credentials + product lookup.

Requires free OAuth2 client credentials (https://developer.kroger.com) via
the ``PRY_KROGER_CLIENT_ID`` and ``PRY_KROGER_CLIENT_SECRET`` env vars. The
client-credentials token is fetched once and cached in-memory (30-minute
expiry, refreshed at 25 minutes).

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from datasets.food_data.grocery_common import (
    _EXCLUDED_EXCEPTIONS,
    _HEADERS,
    _TIMEOUT,
    _clean_name,
    _extract_price,
    _safe_float,
    _today,
)

logger = logging.getLogger(__name__)

_KROGER_OAUTH_URL = "https://api.kroger.com/v1/connect/oauth2/token"
_KROGER_PRODUCTS_URL = "https://api.kroger.com/v1/products"

# Kroger tokens last 30 minutes; refresh a little early to avoid races.
_TOKEN_TTL = 1500.0
_TOKEN_CACHE: dict[str, Any] = {"token": None, "expires_at": 0.0}


def _client_credentials() -> tuple[str, str]:
    """Return (client_id, client_secret) from the environment ('' if unset)."""
    return (
        os.getenv("PRY_KROGER_CLIENT_ID", "").strip(),
        os.getenv("PRY_KROGER_CLIENT_SECRET", "").strip(),
    )


def _clear_token_cache() -> None:
    """Drop the cached Kroger token (used by tests)."""
    _TOKEN_CACHE["token"] = None
    _TOKEN_CACHE["expires_at"] = 0.0


async def _fetch_kroger_token(client: httpx.AsyncClient) -> str | None:
    """OAuth2 client-credentials token for the Kroger API; None on failure."""
    now = time.time()
    cached = _TOKEN_CACHE.get("token")
    if cached and float(_TOKEN_CACHE.get("expires_at", 0.0)) > now + 30:
        return str(cached)
    client_id, client_secret = _client_credentials()
    if not client_id or not client_secret:
        return None
    data = {"grant_type": "client_credentials", "scope": "product.compact"}
    try:
        resp = await client.post(
            _KROGER_OAUTH_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            auth=(client_id, client_secret),
        )
        if resp.status_code >= 400:
            logger.warning("kroger_token_http_error", extra={"status": resp.status_code})
            return None
        payload = resp.json()
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            return None
        expires_in = _safe_float(payload.get("expires_in")) or 1800.0
        _TOKEN_CACHE["token"] = token
        _TOKEN_CACHE["expires_at"] = now + min(expires_in, _TOKEN_TTL)
        return token
    except _EXCLUDED_EXCEPTIONS as exc:
        logger.warning("kroger_token_failed", extra={"error": str(exc)[:120]})
        return None


def _parse_kroger_payload(payload: Any, zip_code: str, limit: int) -> list[dict[str, Any]]:
    """Normalize Kroger /products response into the canonical record shape."""
    records: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return records
    data = payload.get("data")
    if not isinstance(data, list):
        return records
    for product in data:
        if not isinstance(product, dict):
            continue
        items = product.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            price = _extract_price(item.get("price"))
            if price is None:
                continue
            name = _clean_name(
                item.get("description") or product.get("description") or item.get("name")
            )
            if not name:
                continue
            sold_by = item.get("soldBy")
            unit = (
                _clean_name(item.get("size"))
                or (_clean_name(sold_by).lower() if isinstance(sold_by, str) else "")
                or "each"
            )
            records.append(
                {
                    "product": name,
                    "store": "Kroger",
                    "price": price,
                    "currency": "USD",
                    "zip_code": zip_code,
                    "unit": unit,
                    "date": _today(),
                }
            )
            if len(records) >= limit:
                return records
    return records


async def _kroger_prices(query: str, zip_code: str, limit: int) -> list[dict[str, Any]]:
    """Fetch prices from the Kroger API; [] on any failure."""
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            token = await _fetch_kroger_token(client)
            if not token:
                return []
            params = {
                "filter.term": query,
                "filter.locationId": zip_code,
                "filter.limit": str(limit),
            }
            resp = await client.get(
                _KROGER_PRODUCTS_URL,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code >= 400:
                logger.warning("kroger_products_http_error", extra={"status": resp.status_code})
                return []
            return _parse_kroger_payload(resp.json(), zip_code, limit)
    except _EXCLUDED_EXCEPTIONS as exc:
        logger.warning("kroger_prices_failed", extra={"error": str(exc)[:120]})
        return []
