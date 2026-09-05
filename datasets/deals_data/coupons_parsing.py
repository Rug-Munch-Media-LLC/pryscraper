"""Deal-record parsers for deal-aggregator coupon scraping.

Extracts deal records from:

* **JSON-LD** (``application/ld+json`` blocks — ``Product`` / ``Offer`` /
  ``AggregateOffer`` nodes).
* **Embedded JSON** (``<script id="__NEXT_DATA__" type="application/json">``
  blobs, walked recursively for anything that looks like a deal).
* Classic HTML result blocks (Slickdeals ``fpGridBox`` items,
  RetailMeNot ``merchant-coupon`` articles) as a secondary path.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from datasets.deals_data.coupons_common import (
    _clean_text,
    _deal_id,
    _money_float,
    _parse_text_discount,
    _to_float,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

_JSON_LD_RE = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL)
_NEXT_DATA_RE = re.compile(
    r'<script[^>]+id="__NEXT_DATA__"[^>]*type="application/json"[^>]*>(.*?)</script>',
    re.DOTALL,
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
