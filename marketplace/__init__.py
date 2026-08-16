"""Marketplace intelligence scrapers — Amazon, Walmart, TikTok Shop.

This package provides free-tier, keyless product intelligence for the three
highest-revenue marketplace niches:

* :mod:`marketplace.amazon` — Amazon product detail + search via the public
  product/search HTML pages (no API key; optional Rainforest free-tier key
  is read from the environment when present).
* :mod:`marketplace.walmart` — Walmart product detail + search via the
  ``__NEXT_DATA__`` JSON embedded in the public product/search pages.
* :mod:`marketplace.tiktok_shop` — TikTok Shop product detail via the
  unauthenticated web render endpoint, plus a best-effort trending list.

Public functions (imported per module so the identical names on different
providers never collide):

====================  ===========================================
``amazon.get_product(asin)``            → dict
``amazon.search_products(query, limit)``→ list[dict]
``walmart.get_product(product_id)``     → dict
``walmart.search_products(query, limit)``→ list[dict]
``tiktok_shop.get_product(product_id)`` → dict
``tiktok_shop.get_trending(limit)``     → list[dict]
====================  ===========================================

For convenience this package also re-exports every public function with an
unambiguous provider prefix (``amazon_get_product``, ``walmart_search_products``,
…), which is the recommended import for the MCP / REST wiring layer::

    from marketplace import amazon_get_product, walmart_get_product

Contracts:

* **Never raise.** Every public function catches provider/transport/parse
  failures and returns ``{}`` (single product) or ``[]`` (lists) instead.
* **No secrets.** Optional API keys (e.g. ``RAINFOREST_API_KEY`` /
  ``PRY_RAINFOREST_API_KEY``) are read from the environment at call time —
  never hardcoded.
* **Free tier.** Direct scraping of public HTML / embedded JSON by default;
  a Rainforest API key (free tier) is only consulted when scraping fails.

Configuration (env vars, all optional):

* ``PRY_MARKETPLACE_USER_AGENT`` — fixed UA override (default: rotate).
* ``PRY_MARKETPLACE_HONOR_ROBOTS`` — "1" (default) fetches + honors each
  host's robots.txt before requesting product/search pages; set to "0" to
  bypass (needed if a retailer disallows product paths).
* ``PRY_MARKETPLACE_HTTP_RETRIES`` — retries per request (default 2).
* ``PRY_RAINFOREST_API_KEY`` / ``RAINFOREST_API_KEY`` — optional Rainforest
  free-tier key used as an Amazon fallback.
* ``PRY_TIKTOK_TRENDING_PLACEHOLDER`` — "1" returns clearly-marked
  placeholder rows from :func:`tiktok_shop.get_trending` when the bestseller
  page cannot be scraped (default "0" → empty list).

Internal helpers (``_``-prefixed) are shared by the three submodules; they
are not part of the public API.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import random
import re
import time
from typing import Any
from urllib.parse import urlsplit

import httpx
from lxml import html as lxml_html

from client import get_client

logger = logging.getLogger(__name__)

# SystemRandom so UA rotation / jitter is not predictable.
_RNG = random.SystemRandom()

# ── HTTP configuration ─────────────────────────────────────────────────
HTTP_TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=8.0)
ROBOTS_TIMEOUT = httpx.Timeout(connect=4.0, read=6.0, write=6.0, pool=4.0)
RETRY_BASE = 0.5  # seconds — exponential backoff base
MAX_BACKOFF = 3.0  # seconds — backoff cap

# Realistic desktop + mobile user agents for rotation.
_USER_AGENTS: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
)

# ── Shared small helpers ───────────────────────────────────────────────

_WHITESPACE_RE = re.compile(r"\s+")


def _text(value: Any) -> str:
    """Collapse whitespace + unescape HTML entities on scraped text; "" for None."""
    return html.unescape(_WHITESPACE_RE.sub(" ", str(value or "")).strip())


def _to_float(value: Any, default: float = 0.0) -> float:
    """Coerce any numeric input to float; ``default`` on failure."""
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    """Coerce any numeric input to int; ``default`` on failure."""
    try:
        if value is None:
            return default
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default


# Currency symbol → ISO-4217 code (best-effort; $ defaults to USD).
_SYMBOL_CURRENCY: dict[str, str] = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "¥": "CNY",
    "C$": "CAD",
    "CA$": "CAD",
    "A$": "AUD",
    "AU$": "AUD",
}
_PRICE_RE = re.compile(
    r"(?P<sym>\$\s?|€\s?|£\s?|¥\s?|C\$\s?|A\$\s?|CA\$\s?|AU\$\s?)?(?P<num>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)"
)


def _price_parts(text: Any) -> tuple[float, str]:
    """Parse a price string into ``(amount, currency_code)``; (0.0, "") on failure.

    Handles "$1,234.56", "€ 99,90", "45.99", "12.345" (plain number).
    """
    match = _PRICE_RE.search(_text(text))
    if not match:
        return 0.0, ""
    raw = match.group("num")
    if "," in raw and "." in raw:
        raw = raw.replace(",", "")  # 1,234.56
    try:
        amount = float(raw)
    except ValueError:
        return 0.0, ""
    symbol = (match.group("sym") or "").strip()
    return amount, _SYMBOL_CURRENCY.get(symbol, "")


def _first_text(values: Any) -> str:
    """First non-empty text from an lxml text() result list."""
    if not isinstance(values, (list, tuple)):
        return _text(values)
    for value in values:
        cleaned = _text(value)
        if cleaned:
            return cleaned
    return ""


def _lxml_doc(html_text: str) -> Any:
    """Parse HTML into an lxml document; None on any parse failure."""
    if not html_text:
        return None
    try:
        return lxml_html.fromstring(html_text)
    except (ValueError, TypeError):
        return None


def _find_script_json(html_text: str, script_id: str) -> Any:
    """Parse a ``<script id="...">`` block's JSON payload; None on failure."""
    if not html_text:
        return None
    match = re.search(
        rf'<script[^>]*id="{re.escape(script_id)}"[^>]*>(.*?)</script>',
        html_text,
        re.DOTALL | re.IGNORECASE,
    )
    if not match:
        return None
    try:
        return json.loads(match.group(1).strip())
    except ValueError:
        return None


# Walmart redux state: `window.__WML_REDUX_INITIAL_STATE__ = {...};`
_REDUX_RE = re.compile(
    r"window\.__WML_REDUX_INITIAL_STATE__\s*=\s*(\{.*?\})\s*;?\s*</script>",
    re.DOTALL,
)


def _find_redux_state(html_text: str) -> Any:
    """Parse Walmart's ``__WML_REDUX_INITIAL_STATE__`` JSON; None on failure."""
    if not html_text:
        return None
    match = _REDUX_RE.search(html_text)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except ValueError:
        return None


def _is_amazon_block(html_text: str, status: int) -> bool:
    """True when an Amazon response looks like an anti-bot / captcha page."""
    if status in (403, 503):
        return True
    lowered = (html_text or "").lower()
    return any(
        marker in lowered
        for marker in (
            "captcha",
            "robot check",
            "automated access",
            "enter the characters you see below",
            "api-services-support@amazon.com",
        )
    )


# ── UA rotation / robots / HTTP ────────────────────────────────────────


def _rotate_ua() -> str:
    """Pick a user agent: env override, else a random one from the pool."""
    override = os.getenv("PRY_MARKETPLACE_USER_AGENT", "").strip()
    if override:
        return override
    return _RNG.choice(_USER_AGENTS)


def _http_retries() -> int:
    """Retry count per request from env (default 2; min 1)."""
    try:
        return max(1, int(os.getenv("PRY_MARKETPLACE_HTTP_RETRIES", "2")))
    except ValueError:
        return 2


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    """Parse the Retry-After header (seconds); None when absent/invalid."""
    value = resp.headers.get("Retry-After")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _backoff(attempt: int) -> float:
    """Exponential backoff with cap."""
    return min(RETRY_BASE * (2**attempt), MAX_BACKOFF)


async def _fetch_html(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    retries: int | None = None,
    follow_redirects: bool = True,
    request_timeout: httpx.Timeout = HTTP_TIMEOUT,
) -> str | None:
    """GET ``url`` and return the response text; None on any failure.

    Never raises. Rotates the User-Agent per attempt, retries with
    exponential backoff on 429 (honoring Retry-After), 5xx and transport
    errors, and treats any 4xx as a hard failure.
    """
    client = await get_client()
    attempts = retries if retries is not None else _http_retries()
    for attempt in range(attempts):
        try:
            request_headers = {"User-Agent": _rotate_ua()}
            if headers:
                request_headers.update(headers)
            resp = await client.get(
                url,
                params=params,
                headers=request_headers,
                timeout=request_timeout,
                follow_redirects=follow_redirects,
            )
        except httpx.HTTPError as exc:  # transport errors, timeouts
            logger.warning(
                "marketplace_http_error",
                extra={"url": url[:140], "error": str(exc)[:140], "attempt": attempt},
            )
            if attempt + 1 < attempts:
                await asyncio.sleep(_backoff(attempt))
            continue
        if resp.status_code == 429:
            if attempt + 1 < attempts:
                await asyncio.sleep(_retry_after_seconds(resp) or _backoff(attempt))
            continue
        if resp.status_code >= 500:
            if attempt + 1 < attempts:
                await asyncio.sleep(_backoff(attempt))
            continue
        if resp.status_code >= 400:
            return None
        if resp.status_code == 200:
            return resp.text
        return None
    return None


async def _fetch_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    retries: int | None = None,
) -> Any:
    """GET ``url`` and return parsed JSON; None on any failure (never raises)."""
    text = await _fetch_html(url, params=params, headers=headers, retries=retries)
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


# ── robots.txt honoring (Amazon only — spec: rotate UA, honor robots, backoff) ──
_ROBOTS_CACHE: dict[str, tuple[float, bool]] = {}
_ROBOTS_TTL = 3600.0  # seconds


def _honor_robots() -> bool:
    return os.getenv("PRY_MARKETPLACE_HONOR_ROBOTS", "1").lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _robots_rules(text: str) -> tuple[list[str], list[str]]:
    """Parse robots.txt into (allow, disallow) path rules for our UA group."""
    allow: list[str] = []
    disallow: list[str] = []
    group = "*"
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            group = value.lower() or "*"
        elif group in ("*", "prybot"):
            if key == "disallow":
                disallow.append(value)
            elif key == "allow":
                allow.append(value)
    return allow, disallow


def _rule_matches(rule: str, path: str) -> bool:
    """Match a robots rule (``*`` glob) against a URL path prefix."""
    if not rule:
        return False
    pattern = re.escape(rule).replace(r"\*", ".*")
    return re.search(f"^{pattern}", path) is not None


async def _fetch_robots(host: str, path: str) -> bool:
    """Fetch + evaluate robots.txt for one host/path; True (allow) by default."""
    allow: list[str] = []
    disallow: list[str] = []
    try:
        client = await get_client()
        resp = await client.get(
            f"https://{host}/robots.txt",
            headers={"User-Agent": "prybot/3.0"},
            timeout=ROBOTS_TIMEOUT,
            follow_redirects=False,
        )
        if resp.status_code == 200:
            allow, disallow = _robots_rules(resp.text)
    except httpx.HTTPError:
        pass  # robots.txt unreachable → allow (standard convention)
    for rule in allow:
        if _rule_matches(rule, path):
            return True
    return not any(_rule_matches(rule, path) for rule in disallow)


async def _robots_allowed(url: str) -> bool:
    """True when robots.txt permits fetching ``url`` (cached per host)."""
    if not _honor_robots():
        return True
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        path = parts.path or "/"
    except ValueError:
        return True
    if not host:
        return True
    cached = _ROBOTS_CACHE.get(host)
    if cached and time.monotonic() - cached[0] < _ROBOTS_TTL:
        return cached[1]
    allowed = await _fetch_robots(host, path)
    _ROBOTS_CACHE[host] = (time.monotonic(), allowed)
    return allowed


def _clear_robots_cache() -> None:
    """Clear the robots.txt cache (used by tests)."""
    _ROBOTS_CACHE.clear()


# ── Amazon Rainforest fallback (free tier, env key only) ───────────────


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


# ── Public re-exports (provider-prefixed — names collide across modules) ──
from marketplace.amazon import (  # noqa: E402
    get_product as amazon_get_product,
    search_products as amazon_search_products,
)
from marketplace.tiktok_shop import (  # noqa: E402
    get_product as tiktok_get_product,
    get_trending as tiktok_get_trending,
)
from marketplace.walmart import (  # noqa: E402
    get_product as walmart_get_product,
    search_products as walmart_search_products,
)

# Submodules stay importable so consumers can use the per-provider names
# directly: ``from marketplace.amazon import get_product``.
__all__ = [
    "amazon_get_product",
    "amazon_search_products",
    "tiktok_get_product",
    "tiktok_get_trending",
    "walmart_get_product",
    "walmart_search_products",
]
