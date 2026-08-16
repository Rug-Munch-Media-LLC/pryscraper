"""Deal-aggregator coupons: best-effort Slickdeals / RetailMeNot scrape.

Scrapes the public search + store pages of two big deal aggregators and
extracts coupon/deal records from the structured data they embed:

* **JSON-LD** (``application/ld+json`` blocks — ``Product`` / ``Offer`` /
  ``AggregateOffer`` nodes).
* **Embedded JSON** (``<script id="__NEXT_DATA__" type="application/json">``
  blobs, walked recursively for anything that looks like a deal).

Both sites serve JS-heavy pages and sit behind Cloudflare / anti-bot
challenges for datacenter traffic, so in practice the scrapes frequently
yield ``[]``. This is flagged honestly via :func:`blocked_sources` (which
reports which sources looked blocked on the most recent call) rather than
faked. When a page is not blocked the classic HTML result blocks are also
parsed (Slickdeals ``fpGridBox`` items, RetailMeNot ``merchant-coupon``
articles) as a secondary extraction path.

Contract
--------
* :func:`search_deals` — async, never raises, returns a ``list`` of deal
  records (``[]`` on failure / anti-bot blocks).
* :func:`get_store_deals` — async, never raises, same record shape.
* :func:`blocked_sources` — sync, returns the list of sources that looked
  anti-bot-blocked during the most recent search/store call.

Canonical deal record:
``{id, title, store, discount, price, original_price, url, expires,
source}`` where ``discount`` is the percent saved (``float | None``),
``price`` / ``original_price`` are ``float | None`` and ``expires`` is an
ISO-ish string (``""`` when unknown).

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
import hashlib
import json
import logging
import re
import threading
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import httpx

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

# ── endpoints & configuration ──────────────────────────────────────────
_SLICKDEALS_SEARCH_URL = "https://slickdeals.net/newsearch.php"
_SLICKDEALS_STORE_URL = "https://slickdeals.net/store/{store}/"
_RETAILMENOT_SEARCH_URL = "https://www.retailmenot.com/s/{q}"
_RETAILMENOT_STORE_URL = "https://www.retailmenot.com/view/{store}"

_MAX_LIMIT = 100

_TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=8.0)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Backoff tuning (tests monkeypatch these to 0 for speed).
RETRY_BASE = 0.5
MAX_BACKOFF = 2.0
MAX_RETRIES = 1

_JSON_LD_RE = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL)
_NEXT_DATA_RE = re.compile(
    r'<script[^>]+id="__NEXT_DATA__"[^>]*type="application/json"[^>]*>(.*?)</script>',
    re.DOTALL,
)

# Anti-bot challenge markers observed across Cloudflare / Datadome / PX.
_BLOCK_MARKERS = (
    "captcha",
    "cf-chl",
    "cf-browser-verification",
    "cloudflare",
    "px-captcha",
    "attention required",
    "access denied",
    "are you a human",
    "verify you are human",
    "datadome",
)

# Slickdeals classic search-result blocks (li.fpGridBox).
_SD_BLOCK_RE = re.compile(r'<li[^>]*class="[^"]*fpGridBox[^"]*"[^>]*>(.*?)</li>', re.DOTALL)
_SD_TITLE_RE = re.compile(
    r'<a[^>]*class="[^"]*itemTitle[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL
)
_SD_PRICE_RE = re.compile(r'class="[^"]*itemPrice[^"]*"[^>]*>([^<]+)<', re.DOTALL)
_SD_OLD_PRICE_RE = re.compile(r'class="[^"]*itemOldPrice[^"]*"[^>]*>([^<]+)<', re.DOTALL)
_SD_STORE_RE = re.compile(r'class="[^"]*itemStore[^"]*"[^>]*>([^<]+)<', re.DOTALL)

# RetailMeNot coupon-card articles.
_RMN_COUPON_RE = re.compile(
    r'<article[^>]*class="[^"]*merchant-coupon[^"]*"[^>]*>(.*?)</article>', re.DOTALL
)
_RMN_TITLE_RE = re.compile(r'class="[^"]*coupon__title[^"]*"[^>]*>(.*?)</', re.DOTALL)
_RMN_BODY_RE = re.compile(r'class="[^"]*coupon__body[^"]*"[^>]*>(.*?)</', re.DOTALL)
_RMN_EXPIRES_RE = re.compile(
    r"(?:expires|expiration|valid through|offer ends|valid thru)"
    r"[^<A-Za-z0-9]{0,20}"
    r"([A-Za-z]{3,9} \d{1,2},? \d{4}|\d{1,2}[/.]\d{1,2}[/.]\d{4}|"
    r"[A-Za-z]{1,3}\.? ?\d{1,2},? ?\d{4})",
    re.IGNORECASE,
)

# Per-source blocked state from the most recent call (thread-safe).
_BLOCKED: dict[str, bool] = {}
_LOCK = threading.RLock()


# ── low-level helpers ──────────────────────────────────────────────────


def _clamp_limit(limit: Any) -> int:
    """Coerce ``limit`` to an int within [1, _MAX_LIMIT]; default 20."""
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = 20
    return max(1, min(value, _MAX_LIMIT))


def _url_quote(text: str) -> str:
    return quote(text, safe="")


def _to_float(value: Any) -> float | None:
    """Coerce a JSON/text value to float; None when not numeric."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _money_float(raw: Any) -> float | None:
    """Parse a price-ish string like ``"$1,234.56"`` / ``"1 234,56"``."""
    if isinstance(raw, (int, float)):
        return _to_float(raw)
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    text = re.sub(r"[^\d.,\-]", "", text)
    if not text or text in {"-", "."}:
        return None
    if "," in text and "." in text:
        # "$1,234.56" → strip the thousands separator, keep the decimals.
        if text.rfind(",") < text.rfind("."):
            text = text.replace(",", "")
        else:
            text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _percent_discount(price: float | None, original: float | None) -> float | None:
    """Percent saved between a current price and its original price."""
    if price is None or original is None or original <= 0 or price <= 0:
        return None
    return round((1.0 - price / original) * 100.0, 1)


def _parse_text_discount(price: float | None, original: float | None, text: str) -> float | None:
    """Fall back to a ``% off`` / ``$X off`` literal found in deal text."""
    if _percent_discount(price, original) is not None:
        return _percent_discount(price, original)
    pct = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if pct:
        return float(pct.group(1))
    off = re.search(r"\$\s*(\d+(?:\.\d+)?)\s*off", text, re.IGNORECASE)
    if off and price is not None and price > 0:
        return round(float(off.group(1)) / price * 100.0, 1)
    return None


def _clean_text(raw: Any) -> str:
    """Strip tags/whitespace from scraped text."""
    text = re.sub(r"<[^>]+>", " ", str(raw or ""))
    return re.sub(r"\s+", " ", text).strip()


def _deal_id(source: str, url: str, title: str) -> str:
    """Deterministic deal id from source + url (fallback: title hash)."""
    seed = url or title or source
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _is_blocked_html(raw: str) -> bool:
    """Heuristic: does this page look like an anti-bot challenge page?"""
    lowered = (raw or "").lower()
    return any(marker in lowered for marker in _BLOCK_MARKERS)


async def _sleep_backoff(attempt: int) -> None:
    """Sleep with capped exponential backoff (knobs are test-overridable)."""
    if attempt <= 0 or RETRY_BASE <= 0 or MAX_BACKOFF <= 0:
        return
    await asyncio.sleep(min(MAX_BACKOFF, RETRY_BASE * (2**attempt)))


async def _fetch(url: str, params: dict[str, str] | None = None) -> str:
    """GET a URL with bounded backoff retries; never raises ('' on failure)."""
    last_error = ""
    for attempt in range(MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
            ) as client:
                resp = await client.get(url, params=params)
            if resp.status_code == 429:
                last_error = "HTTP 429 (rate limited)"
                await _sleep_backoff(attempt)
                continue
            if resp.status_code >= 400:
                last_error = f"HTTP {resp.status_code}"
                await _sleep_backoff(attempt)
                continue
            return resp.text
        except (httpx.HTTPError, OSError) as exc:
            last_error = str(exc)[:120]
            await _sleep_backoff(attempt)
    logger.warning("deals_fetch_failed", extra={"url": url[:120], "error": last_error})
    return ""


# ── structured-data parsing ────────────────────────────────────────────


def _walk_dicts(obj: Any) -> Iterator[dict[str, Any]]:
    """Yield every dict (at any depth) inside a parsed JSON tree."""
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk_dicts(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk_dicts(value)


def _parse_json_ld(raw: str) -> list[dict[str, Any]]:
    """Parse every JSON-LD block in an HTML page into dicts."""
    out: list[dict[str, Any]] = []
    for match in _JSON_LD_RE.finditer(raw):
        text = match.group(1).strip()
        if not text:
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            out.append(data)
        elif isinstance(data, list):
            out.extend(item for item in data if isinstance(item, dict))
    return out


def _parse_next_data(raw: str) -> dict[str, Any]:
    """Parse a ``__NEXT_DATA__`` JSON blob into a dict ({} on failure)."""
    match = _NEXT_DATA_RE.search(raw)
    if not match:
        return {}
    try:
        data = json.loads(match.group(1).strip())
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _offer_prices(offers: Any) -> tuple[float | None, float | None]:
    """Extract (price, original_price) from a JSON-LD ``offers`` node."""
    if isinstance(offers, dict):
        price = _to_float(offers.get("price") or offers.get("lowPrice"))
        original = _to_float(
            offers.get("highPrice") or (offers.get("priceSpecification") or {}).get("price", 0) or 0
        )
        if original is None or (original is not None and original == price):
            original = None
        return price, original
    if isinstance(offers, list):
        prices: list[float] = []
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            parsed = _to_float(offer.get("price"))
            if parsed is not None:
                prices.append(parsed)
        if not prices:
            return None, None
        return min(prices), (max(prices) if len(prices) > 1 else None)
    return None, None


def _seller_name(obj: dict[str, Any]) -> str:
    """Best-effort seller/store from JSON-LD ``offers`` / ``seller`` / ``brand``."""
    offers = obj.get("offers")
    if isinstance(offers, dict):
        seller = offers.get("seller")
        if isinstance(seller, dict) and seller.get("name"):
            return str(seller["name"])
        if offers.get("sellerName"):
            return str(offers["sellerName"])
    brand = obj.get("brand")
    if isinstance(brand, dict) and brand.get("name"):
        return str(brand["name"])
    seller = obj.get("seller")
    if isinstance(seller, dict) and seller.get("name"):
        return str(seller["name"])
    if isinstance(brand, str):
        return brand
    return ""


def _map_jsonld_deal(source: str, obj: dict[str, Any]) -> dict[str, Any] | None:
    """Map a JSON-LD / embedded-JSON dict that looks like a deal onto a record."""
    title = str(obj.get("name") or obj.get("title") or "").strip()
    if not title:
        return None
    url = str(obj.get("url") or "")
    if not url:
        return None
    price, original = _offer_prices(obj.get("offers"))
    if price is None:
        # Bare coupon nodes carry no offer — only accept them via HTML path.
        return None
    store = _seller_name(obj)
    offers_node = obj.get("offers")
    expires = str(
        obj.get("priceValidUntil")
        or (offers_node.get("priceValidUntil") if isinstance(offers_node, dict) else "")
        or obj.get("endDate")
        or ""
    )
    discount = _parse_text_discount(price, original, title)
    return {
        "id": _deal_id(source, url, title),
        "title": title,
        "store": store,
        "discount": discount,
        "price": price,
        "original_price": original,
        "url": url,
        "expires": expires,
        "source": source,
    }


def _parse_structured_deals(source: str, raw: str) -> list[dict[str, Any]]:
    """Extract deal records from JSON-LD + ``__NEXT_DATA__`` blocks."""
    out: list[dict[str, Any]] = []
    for block in _parse_json_ld(raw):
        for d in _walk_dicts(block):
            if "@type" not in d:
                continue
            record = _map_jsonld_deal(source, d)
            if record:
                out.append(record)
    for d in _walk_dicts(_parse_next_data(raw)):
        record = _map_jsonld_deal(source, d)
        if record:
            out.append(record)
    return out


def _parse_slickdeals_html(raw: str) -> list[dict[str, Any]]:
    """Extract deals from classic Slickdeals ``li.fpGridBox`` result blocks."""
    out: list[dict[str, Any]] = []
    for block in _SD_BLOCK_RE.finditer(raw):
        body = block.group(1)
        title_match = _SD_TITLE_RE.search(body)
        if not title_match:
            continue
        url = title_match.group(1).strip()
        title = _clean_text(title_match.group(2))
        if not title:
            continue
        if not url.startswith("http"):
            url = f"https://slickdeals.net{url}"
        price_match = _SD_PRICE_RE.search(body)
        price = _money_float(price_match.group(1) if price_match else None)
        old_price_match = _SD_OLD_PRICE_RE.search(body)
        original = _money_float(old_price_match.group(1) if old_price_match else None)
        store_match = _SD_STORE_RE.search(body)
        store = _clean_text(store_match.group(1)) if store_match else ""
        out.append(
            {
                "id": _deal_id("slickdeals", url, title),
                "title": title,
                "store": store,
                "discount": _parse_text_discount(price, original, title),
                "price": price,
                "original_price": original,
                "url": url,
                "expires": "",
                "source": "slickdeals",
            }
        )
    return out


def _parse_retailmenot_html(raw: str) -> list[dict[str, Any]]:
    """Extract coupons from RetailMeNot ``article.merchant-coupon`` cards."""
    out: list[dict[str, Any]] = []
    for match in _RMN_COUPON_RE.finditer(raw):
        body = match.group(1)
        title_match = _RMN_TITLE_RE.search(body)
        title = _clean_text(title_match.group(1)) if title_match else ""
        if not title:
            continue
        body_match = _RMN_BODY_RE.search(body)
        description = _clean_text(body_match.group(1)) if body_match else ""
        # RetailMeNot coupon cards share the merchant landing URL — per-coupon
        # deep links are not exposed in the static markup. Keep url "" so the
        # dedupe (by url, then id) does not collapse distinct coupons.
        url = ""
        expires_match = _RMN_EXPIRES_RE.search(body + " " + description)
        expires = expires_match.group(1).strip() if expires_match else ""
        full_text = f"{title} {description}"
        price_match = re.search(r"\$\s*(\d+(?:\.\d+)?)", full_text)
        price = _money_float(price_match.group(1) if price_match else None)
        store = ""
        merchant_match = re.search(r'class="[^"]*merchant-name[^"]*"[^>]*>([^<]+)<', body)
        if merchant_match:
            store = _clean_text(merchant_match.group(1))
        out.append(
            {
                "id": _deal_id("retailmenot", url or title, title),
                "title": title,
                "store": store,
                "discount": _parse_text_discount(price, None, full_text),
                "price": price,
                "original_price": None,
                "url": url,
                "expires": expires,
                "source": "retailmenot",
            }
        )
    return out


def _dedupe_deals(records: list[dict[str, Any]], bounded: int) -> list[dict[str, Any]]:
    """Dedupe by url (then id) and cap at ``bounded``."""
    seen_urls: set[str] = set()
    seen_ids: set[str] = set()
    out: list[dict[str, Any]] = []
    for record in records:
        url = str(record.get("url") or "")
        deal_id = str(record.get("id") or "")
        if url and url in seen_urls:
            continue
        if deal_id in seen_ids:
            continue
        if url:
            seen_urls.add(url)
        seen_ids.add(deal_id)
        out.append(record)
        if len(out) >= bounded:
            break
    return out


def blocked_sources() -> list[str]:
    """Sources that looked anti-bot-blocked on the most recent call.

    Sync helper for observability (deal bots can surface this in their
    status). Cleared at the start of every search/store call.
    """
    with _LOCK:
        return [source for source, blocked in _BLOCKED.items() if blocked]


def _mark_blocked(source: str, blocked: bool) -> None:
    with _LOCK:
        _BLOCKED[source] = blocked


# ── public API ─────────────────────────────────────────────────────────


async def search_deals(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search Slickdeals + RetailMeNot for deals matching ``query``.

    Best-effort: both aggregators are anti-bot / JS-heavy, so results may
    legitimately be ``[]`` (check :func:`blocked_sources` to tell a block
    apart from a genuinely empty result set). Dedupes by url and caps at
    ``limit``. Async, never raises.
    """
    text = (query or "").strip()
    bounded = _clamp_limit(limit)
    with _LOCK:
        _BLOCKED.clear()
    if not text:
        return []
    out: list[dict[str, Any]] = []
    # Slickdeals search page (classic results + structured data).
    raw = await _fetch(_SLICKDEALS_SEARCH_URL, params={"q": text, "searcharea": "deals"})
    if raw:
        if _is_blocked_html(raw):
            logger.warning("deals_antibot_blocked", extra={"source": "slickdeals"})
            _mark_blocked("slickdeals", True)
        else:
            out.extend(_parse_structured_deals("slickdeals", raw))
            out.extend(_parse_slickdeals_html(raw))
    # RetailMeNot search page (coupon cards + structured data).
    raw = await _fetch(_RETAILMENOT_SEARCH_URL.format(q=_url_quote(text)))
    if raw:
        if _is_blocked_html(raw):
            logger.warning("deals_antibot_blocked", extra={"source": "retailmenot"})
            _mark_blocked("retailmenot", True)
        else:
            out.extend(_parse_structured_deals("retailmenot", raw))
            out.extend(_parse_retailmenot_html(raw))
    return _dedupe_deals(out, bounded)


async def get_store_deals(store: str, limit: int = 20) -> list[dict[str, Any]]:
    """Fetch deals/coupons for one retailer from Slickdeals + RetailMeNot.

    ``store`` may be a bare name (``"amazon"``) — both aggregators accept
    slugs. Same honest-degradation contract as :func:`search_deals`.
    Async, never raises.
    """
    slug = (store or "").strip().lower()
    bounded = _clamp_limit(limit)
    with _LOCK:
        _BLOCKED.clear()
    if not slug:
        return []
    out: list[dict[str, Any]] = []
    # Slickdeals store landing page.
    raw = await _fetch(_SLICKDEALS_STORE_URL.format(store=_url_quote(slug)))
    if raw:
        if _is_blocked_html(raw):
            logger.warning("deals_antibot_blocked", extra={"source": "slickdeals"})
            _mark_blocked("slickdeals", True)
        else:
            out.extend(_parse_structured_deals("slickdeals", raw))
            out.extend(_parse_slickdeals_html(raw))
    # RetailMeNot store landing page (/view/{store}).
    raw = await _fetch(_RETAILMENOT_STORE_URL.format(store=_url_quote(slug)))
    if raw:
        if _is_blocked_html(raw):
            logger.warning("deals_antibot_blocked", extra={"source": "retailmenot"})
            _mark_blocked("retailmenot", True)
        else:
            out.extend(_parse_structured_deals("retailmenot", raw))
            out.extend(_parse_retailmenot_html(raw))
    return _dedupe_deals(out, bounded)
