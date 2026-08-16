"""Grocery prices by ZIP — Kroger API + Walmart store-scrape fallback.

Two free sources are aggregated here:

* **Kroger API** (``api.kroger.com``) — the market-standard grocery product
  + pricing API. Requires **free** OAuth2 client credentials
  (https://developer.kroger.com) via the ``PRY_KROGER_CLIENT_ID`` and
  ``PRY_KROGER_CLIENT_SECRET`` env vars. The client-credentials token is
  fetched once and cached in-memory (30-minute expiry, refreshed at 25
  minutes). Products are looked up with ``filter.term`` +
  ``filter.locationId`` (ZIP). Used whenever both keys are configured.
* **Walmart store scrape** (``www.walmart.com/search``) — no key, no quota.
  The search page embeds product/price data in the
  ``window.__WML_REDUX_INITIAL_STATE__`` JSON blob; we extract
  ``name``/``price`` pairs by walking that JSON (with a signature regex
  fallback for layout changes). Walmart aggressively blocks datacenter
  traffic, so this frequently returns ``[]`` in practice — treat results as
  best-effort. Used only when Kroger returns nothing.

Contract
--------
* :func:`get_grocery_prices` — async, never raises, returns a ``list``
  (``[]`` on failure). One record per (product, store).

Result shape::

    {
        "product": "Galaxy 9, 22 oz",
        "store": "Kroger",
        "price": 3.49,
        "currency": "USD",
        "zip_code": "45202",
        "unit": "1 LB",
        "date": "2026-08-16",
    }

``unit`` is the retailer's size/sold-by string ("1 LB", "2 L", "each")
or ``"each"`` when unknown. ``date`` is the UTC date the price was
observed.

Anti-bot honesty: scraping sources are parsed with signature-based
extractors over embedded JSON, mirroring the travel/commerce modules'
approach. When a site changes layout or blocks the request, output
silently degrades to ``[]`` — never an exception.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import html
import json
import logging
import os
import re
import time
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_KROGER_OAUTH_URL = "https://api.kroger.com/v1/connect/oauth2/token"
_KROGER_PRODUCTS_URL = "https://api.kroger.com/v1/products"
_WALMART_SEARCH_URL = "https://www.walmart.com/search"

_TIMEOUT = httpx.Timeout(connect=8.0, read=15.0, write=10.0, pool=8.0)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Kroger tokens last 30 minutes; refresh a little early to avoid races.
_TOKEN_TTL = 1500.0
_TOKEN_CACHE: dict[str, Any] = {"token": None, "expires_at": 0.0}

_ZIP_RE = re.compile(r"^\d{5}(?:-\d{4})?$")

# Walmart embeds product state in a single REDUX script.
_WALMART_REDUX_RE = re.compile(r"window\.__WML_REDUX_INITIAL_STATE__\s*=\s*", re.IGNORECASE)
# Fallback: flat JSON-ish product blocks containing name + currentPrice.
_WALMART_BLOCK_RE = re.compile(
    r'\{"name"\s*:\s*"([^"]+)"(?:.*?)"currentPrice"\s*:\s*([\d.]+)', re.DOTALL
)

_EXCLUDED_EXCEPTIONS = (
    httpx.HTTPError,
    OSError,
    json.JSONDecodeError,
    ValueError,
    TypeError,
    KeyError,
    IndexError,
    re.error,
)


def _client_credentials() -> tuple[str, str]:
    """Return (client_id, client_secret) from the environment ('' if unset)."""
    return (
        os.getenv("PRY_KROGER_CLIENT_ID", "").strip(),
        os.getenv("PRY_KROGER_CLIENT_SECRET", "").strip(),
    )


def _valid_zip(zip_code: str) -> bool:
    return bool(_ZIP_RE.fullmatch(zip_code.strip()))


def _clean_name(value: Any) -> str:
    """Collapse whitespace / HTML entities in a product name; '' if unusable."""
    if not isinstance(value, str):
        return ""
    cleaned = re.sub(r"\s+", " ", html.unescape(value)).strip()
    return cleaned[:200]


def _safe_float(value: Any) -> float | None:
    """Parse a price from a number or a ``$9.99``-style string; None on failure."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    cleaned = value.strip().replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not match:
        return None
    try:
        return round(float(match.group(0)), 2)
    except ValueError:
        return None


def _extract_price(price_info: Any) -> float | None:
    """Best price from a Kroger/Walmart ``price`` object or bare number."""
    if isinstance(price_info, (int, float, str)):
        return _safe_float(price_info)
    if not isinstance(price_info, dict):
        return None
    for key in ("regular", "promo", "currentPrice", "price", "amount", "displayPrice"):
        value = price_info.get(key)
        if value is None:
            continue
        price = _safe_float(value)
        if price is not None:
            return price
    return None


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _clear_token_cache() -> None:
    """Drop the cached Kroger token (used by tests)."""
    _TOKEN_CACHE["token"] = None
    _TOKEN_CACHE["expires_at"] = 0.0


# ── Kroger ──────────────────────────────────────────────────────────────


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


# ── Walmart ─────────────────────────────────────────────────────────────


def _walmart_redux_json(html_text: str) -> str:
    """Slice the REDUX state JSON out of a Walmart page (brace-matched)."""
    match = _WALMART_REDUX_RE.search(html_text)
    if not match:
        return ""
    start = match.end()
    if start >= len(html_text) or html_text[start] != "{":
        return ""
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(html_text)):
        ch = html_text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return html_text[start : i + 1]
    return ""


def _walk_products(
    node: Any,
    records: list[dict[str, Any]],
    seen: set[tuple[str, float]],
    zip_code: str,
    limit: int,
) -> None:
    """Recursively collect Walmart product dicts (name + price) from REDUX JSON."""
    if len(records) >= limit:
        return
    if isinstance(node, list):
        for child in node:
            _walk_products(child, records, seen, zip_code, limit)
            if len(records) >= limit:
                return
        return
    if not isinstance(node, dict):
        return
    name = node.get("name")
    if isinstance(name, str) and name and "price" in node:
        price = _extract_price(node.get("price"))
        if price is not None:
            key = (_clean_name(name), price)
            if key not in seen:
                seen.add(key)
                records.append(
                    {
                        "product": key[0],
                        "store": "Walmart",
                        "price": price,
                        "currency": "USD",
                        "zip_code": zip_code,
                        "unit": "each",
                        "date": _today(),
                    }
                )
    for value in node.values():
        _walk_products(value, records, seen, zip_code, limit)
        if len(records) >= limit:
            return


def _parse_walmart_html(html_text: str, zip_code: str, limit: int) -> list[dict[str, Any]]:
    """Normalize a Walmart search page into the canonical record shape."""
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, float]] = set()
    redux = _walmart_redux_json(html_text)
    if redux:
        try:
            _walk_products(json.loads(redux), records, seen, zip_code, limit)
        except _EXCLUDED_EXCEPTIONS as exc:
            logger.warning("walmart_redux_parse_failed", extra={"error": str(exc)[:120]})
    if records:
        return records[:limit]
    # Signature fallback when the REDUX blob shape changes.
    for match in _WALMART_BLOCK_RE.finditer(html_text):
        name = _clean_name(match.group(1))
        price = _safe_float(match.group(2))
        if not name or price is None or (name, price) in seen:
            continue
        seen.add((name, price))
        records.append(
            {
                "product": name,
                "store": "Walmart",
                "price": price,
                "currency": "USD",
                "zip_code": zip_code,
                "unit": "each",
                "date": _today(),
            }
        )
        if len(records) >= limit:
            break
    return records


async def _walmart_prices(query: str, zip_code: str, limit: int) -> list[dict[str, Any]]:
    """Scrape prices from a Walmart search page; [] on any failure."""
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            resp = await client.get(_WALMART_SEARCH_URL, params={"q": query})
            if resp.status_code >= 400:
                logger.warning("walmart_http_error", extra={"status": resp.status_code})
                return []
            return _parse_walmart_html(resp.text, zip_code, limit)
    except _EXCLUDED_EXCEPTIONS as exc:
        logger.warning("walmart_prices_failed", extra={"error": str(exc)[:120]})
        return []


# ── Public contract ─────────────────────────────────────────────────────


async def get_grocery_prices(query: str, zip_code: str, limit: int = 20) -> list[dict[str, Any]]:
    """Grocery prices by ZIP. Async, never raises, ``[]`` on failure.

    Tries the Kroger API first (when ``PRY_KROGER_CLIENT_ID`` /
    ``PRY_KROGER_CLIENT_SECRET`` are configured); when Kroger returns
    nothing it falls back to a Walmart search-page scrape.
    """
    query = (query or "").strip()
    zip_code = (zip_code or "").strip()
    if not query or not _valid_zip(zip_code) or limit <= 0:
        return []
    try:
        results = await _kroger_prices(query, zip_code, limit)
        if results:
            return results[:limit]
    except _EXCLUDED_EXCEPTIONS as exc:
        logger.warning("grocery_kroger_failed", extra={"error": str(exc)[:120]})
    try:
        results = await _walmart_prices(query, zip_code, limit)
        return results[:limit]
    except _EXCLUDED_EXCEPTIONS as exc:
        logger.warning("grocery_walmart_failed", extra={"error": str(exc)[:120]})
        return []
