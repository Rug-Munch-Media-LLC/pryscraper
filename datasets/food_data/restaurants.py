"""Restaurant menus — menu-page JSON-LD extraction + HTML price fallback.

Free, keyless sources are used here:

1. **Search** — the menu page is located with a DuckDuckGo HTML search
   (``html.duckduckgo.com/html``, no key, no quota) for
   ``"{name} {location} menu"``. The first 5 organic result URLs are
   candidates.
2. **JSON-LD** — each candidate page is scanned for
   ``application/ld+json`` blocks. Menu-structured schema
   (``Menu`` / ``MenuSection`` / ``MenuItem`` with ``offers.price``) is
   extracted first.
3. **HTML fallback** — when no usable JSON-LD is found, a signature-based
   HTML parser pulls menu lines (``Item $9.99``) and heading categories
   (h1/h2/h3) out of the rendered text.

DuckDuckGo HTML search and most restaurant sites aggressively rate-limit
datacenter traffic; when search or the page fetch is blocked the honest
result is ``{}`` — never a fabricated menu.

Contract
--------
* :func:`get_restaurant_menu` — async, never raises, returns a ``dict``
  (``{}`` on failure).

Result shape::

    {
        "restaurant": "Joe's Diner",
        "location": "Cincinnati, OH",
        "menu": [
            {
                "item": "Classic Burger",
                "price": 12.99,
                "description": "Angus beef, cheddar, lettuce",
                "category": "Burgers",
            },
        ],
        "source": "https://example.com/menu",
    }

``price`` is the parsed float when the page exposes one; menu lines
without a detectable price are omitted. ``description`` and ``category``
default to ``None`` / ``"Menu"``.

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
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

logger = logging.getLogger(__name__)

_DDG_HTML_URL = "https://html.duckduckgo.com/html/"
_MAX_RESULTS = 5
_MAX_MENU_ITEMS = 20

_TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=8.0)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_JSONLD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
_RESULT_LINK_RE = re.compile(r'class="result__a"[^>]*href="([^"]+)"', re.IGNORECASE)
_ITEM_LINE_RE = re.compile(r"^(.*?)\s*\$(\d+(?:\.\d{2})?)\s*$")
_CATEGORY_HEADING_RE = re.compile(
    r"^(menu|starters|appetizers|entrees|mains|desserts|drinks|beverages|"
    r"sides|breakfast|lunch|dinner|pizza|burgers|sandwiches|salads|specials|"
    r"kids|children|combos|tacos|pasta|seafood|steaks|soups|wraps|bowls)(?:[^a-z]|$)",
    re.IGNORECASE,
)
# Final fallback: any "Item $9.99" pattern in the visible text.
_PRICE_INLINE_RE = re.compile(r"([A-Za-z][^$\n]{2,90}?)\s*\$(\d+(?:\.\d{2})?)")

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


def _clean_text(value: Any, max_len: int = 200) -> str:
    """Collapse whitespace / HTML entities; '' if unusable."""
    if not isinstance(value, str):
        return ""
    cleaned = re.sub(r"\s+", " ", html.unescape(value)).strip()
    return cleaned[:max_len]


def _to_price(value: Any) -> float | None:
    """Parse ``$9.99`` / ``9.99`` / numbers to a float; None on failure."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    match = re.search(r"\d+(?:\.\d{2})?", value.replace(",", ""))
    if not match:
        return None
    try:
        return round(float(match.group(0)), 2)
    except ValueError:
        return None


def _offer_price(offers: Any) -> float | None:
    """Best price from a JSON-LD ``offers`` node (dict or list)."""
    if isinstance(offers, list):
        for offer in offers:
            price = _offer_price(offer)
            if price is not None:
                return price
        return None
    if not isinstance(offers, dict):
        return _to_price(offers)
    for key in ("price", "lowPrice", "highPrice"):
        value = offers.get(key)
        if value is None:
            continue
        price = _to_price(value)
        if price is not None:
            return price
    return None


def _type_names(node_type: Any) -> list[str]:
    if isinstance(node_type, str):
        return [node_type]
    if isinstance(node_type, list):
        return [str(t) for t in node_type if isinstance(t, str)]
    return []


async def _fetch(url: str, params: dict[str, str] | None = None) -> str:
    """GET a page with a browser UA; '' on HTTP/network failure."""
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
        ) as client:
            resp = await client.get(url, params=params)
        if resp.status_code >= 400:
            logger.warning(
                "restaurant_fetch_http_error", extra={"status": resp.status_code, "url": url[:120]}
            )
            return ""
        return resp.text
    except (httpx.HTTPError, OSError) as exc:
        logger.warning("restaurant_fetch_failed", extra={"url": url[:120], "error": str(exc)[:120]})
        return ""


# ── Source discovery ────────────────────────────────────────────────────


def _decode_ddg_url(href: str) -> str:
    """Unwrap a DuckDuckGo result href to the underlying page URL."""
    href = html.unescape(href)
    if "uddg=" not in href:
        return href if href.startswith("http") else ""
    try:
        query = urlparse(href).query
        return parse_qs(query).get("uddg", [""])[0] or ""
    except (ValueError, TypeError):
        return ""


async def _search_menu_urls(name: str, location: str) -> list[str]:
    """Locate candidate menu page URLs via DuckDuckGo HTML search."""
    query = " ".join(part for part in (name, location, "menu") if part.strip())
    page = await _fetch(_DDG_HTML_URL, params={"q": query})
    if not page:
        return []
    urls: list[str] = []
    for href in _RESULT_LINK_RE.findall(page):
        url = _decode_ddg_url(href)
        if not url or not url.startswith(("http://", "https://")):
            continue
        host = urlparse(url).netloc.lower()
        if "duckduckgo.com" in host or "duck.co" in host:
            continue
        if url not in urls:
            urls.append(url)
        if len(urls) >= _MAX_RESULTS:
            break
    return urls


# ── JSON-LD extraction ──────────────────────────────────────────────────


def _jsonld_extract(
    node: Any,
    category: str = "Menu",
    out: list[dict[str, Any]] | None = None,
    seen: set[tuple[str, float]] | None = None,
) -> list[dict[str, Any]]:
    """Recursively collect menu items from JSON-LD ``Menu`` schema nodes."""
    if out is None:
        out = []
    if seen is None:
        seen = set()
    if isinstance(node, list):
        for child in node:
            _jsonld_extract(child, category, out, seen)
        return out
    if not isinstance(node, dict):
        return out
    type_names = _type_names(node.get("@type"))
    name = _clean_text(node.get("name"), max_len=200)
    if any(t in ("Menu", "MenuSection") for t in type_names):
        section_category = name or category
        for key in ("hasMenuItems", "hasMenuItem", "hasMenuSection", "hasPart", "itemListElement"):
            _jsonld_extract(node.get(key), section_category, out, seen)
        for key in ("hasMenu", "menu"):
            _jsonld_extract(node.get(key), section_category, out, seen)
        return out
    price = _offer_price(node.get("offers"))
    if price is not None and name:
        item_key = (name, price)
        if item_key not in seen:
            seen.add(item_key)
            out.append(
                {
                    "item": name,
                    "price": price,
                    "description": _clean_text(node.get("description"), max_len=300) or None,
                    "category": category or "Menu",
                }
            )
        return out
    for key in ("hasMenu", "menu"):
        _jsonld_extract(node.get(key), category, out, seen)
    return out


def _parse_json_ld(html_text: str) -> list[dict[str, Any]]:
    """Extract menu items from ``application/ld+json`` blocks."""
    items: list[dict[str, Any]] = []
    for block in _JSONLD_RE.findall(html_text):
        try:
            payload = json.loads(block)
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
        _jsonld_extract(payload, out=items)
        if len(items) >= _MAX_MENU_ITEMS:
            break
    return items[:_MAX_MENU_ITEMS]


# ── HTML fallback ───────────────────────────────────────────────────────


def _visible_lines(html_text: str) -> list[str]:
    """Strip scripts/styles/tags and return non-empty text lines."""
    cleaned = re.sub(
        r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html_text, flags=re.DOTALL | re.IGNORECASE
    )
    cleaned = re.sub(r"<[^>]+>", "\n", cleaned)
    return [html.unescape(line).strip() for line in cleaned.splitlines() if line.strip()]


def _parse_html_menu(html_text: str) -> list[dict[str, Any]]:
    """Signature HTML parse: heading categories + ``Item $9.99`` lines."""
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, float]] = set()
    category = "Menu"
    for line in _visible_lines(html_text):
        match = _ITEM_LINE_RE.match(line)
        if match:
            name = _clean_text(match.group(1), max_len=120)
            price = _to_price(match.group(2))
            if name and price is not None and (name, price) not in seen:
                seen.add((name, price))
                items.append(
                    {"item": name, "price": price, "description": None, "category": category}
                )
                if len(items) >= _MAX_MENU_ITEMS:
                    break
        elif len(line) <= 80 and _CATEGORY_HEADING_RE.match(line):
            category = line.title()
    if items:
        return items
    # Final fallback: inline "Item $9.99" anywhere in the visible text.
    text = "\n".join(_visible_lines(html_text))
    for match in _PRICE_INLINE_RE.finditer(text):
        name = _clean_text(match.group(1), max_len=120)
        price = _to_price(match.group(2))
        if not name or price is None or (name, price) in seen:
            continue
        seen.add((name, price))
        items.append({"item": name, "price": price, "description": None, "category": "Menu"})
        if len(items) >= _MAX_MENU_ITEMS:
            break
    return items


# ── Public contract ─────────────────────────────────────────────────────


async def get_restaurant_menu(name: str, location: str = "") -> dict[str, Any]:
    """Restaurant menu by name (+ optional location). Async, never raises,
    ``{}`` on failure."""
    name = (name or "").strip()
    location = (location or "").strip()
    if not name:
        return {}
    try:
        for url in await _search_menu_urls(name, location):
            page = await _fetch(url)
            if not page:
                continue
            menu = _parse_json_ld(page)
            if not menu:
                menu = _parse_html_menu(page)
            if menu:
                return {
                    "restaurant": name,
                    "location": location,
                    "menu": menu,
                    "source": url,
                }
        return {}
    except _EXCLUDED_EXCEPTIONS as exc:
        logger.warning(
            "restaurant_menu_failed", extra={"name": name[:120], "error": str(exc)[:120]}
        )
        return {}
