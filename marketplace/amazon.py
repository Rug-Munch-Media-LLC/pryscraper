"""Amazon marketplace scraper — product detail + search (keyless).

Fetches the public product page (``https://www.amazon.com/dp/{asin}``) and
search results page (``https://www.amazon.com/s?k={query}``) with UA
rotation, robots.txt honoring, and exponential backoff, then normalizes the
extracted fields into the shared marketplace schema.

Optional Rainforest free-tier API key (``PRY_RAINFOREST_API_KEY`` /
``RAINFOREST_API_KEY`` env) is consulted only when direct scraping fails —
never hardcoded.

Contract:

* ``get_product(asin)`` → ``{asin,title,price,currency,buy_box,brand,rating,
  review_count,bsr,category,offers,url}`` (``{}`` on failure).
* ``search_products(query, limit=20)`` → list of the same shape (``[]`` on
  failure).

Never raises.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
import re
from typing import Any

from marketplace import (
    _amazon_via_rainforest,
    _fetch_html,
    _first_text,
    _is_amazon_block,
    _lxml_doc,
    _price_parts,
    _robots_allowed,
    _text,
    _to_float,
    _to_int,
)

logger = logging.getLogger(__name__)

AMAZON_BASE = "https://www.amazon.com"

# Uppercase alphanumeric 10-char ASIN (Amazon product id).
_ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")


def _valid_asin(asin: str) -> bool:
    return bool(asin and _ASIN_RE.match(asin.strip().upper()))


def _amazon_price(doc: Any) -> tuple[float, str]:
    """Extract the (non-strikethrough) price from the product page."""
    for expr in (
        # Deal / "priceToPay" block first, then any non-strike `.a-price`.
        '//span[contains(@class,"priceToPay")]//span[contains(@class,"a-offscreen")]/text()',
        '//span[contains(@class,"a-price") and not(contains(@class,"a-text-price"))]//span[contains(@class,"a-offscreen")]/text()',
        '//span[contains(@class,"a-price")]//span[contains(@class,"a-offscreen")]/text()',
    ):
        for raw in doc.xpath(expr):
            amount, currency = _price_parts(raw)
            if amount > 0:
                return amount, currency
    return 0.0, ""


def _amazon_rating(doc: Any) -> float:
    raw = _first_text(doc.xpath('//span[@id="acrPopover"]//span[@class="a-icon-alt"]/text()'))
    if not raw:
        raw = _first_text(doc.xpath('//span[contains(@class,"a-icon-alt")]/text()'))
    match = re.search(r"([\d.]+)", raw)
    return _to_float(match.group(1) if match else None)


def _amazon_review_count(doc: Any) -> int:
    raw = _first_text(doc.xpath('//span[@id="acrCustomerReviewText"]/text()'))
    if not raw:
        raw = _first_text(doc.xpath('//a[@id="acrCustomerReviewLink"]//text()'))
    match = re.search(r"([\d,]+)", raw)
    return _to_int(match.group(1).replace(",", "") if match else None)


def _amazon_bsr_category(doc: Any, html_text: str) -> tuple[int, str]:
    """Best Sellers Rank + category from the detail bullets / page text."""
    # Preferred: the detail-bullets row (th/td pair) — tags separate the
    # label from the value, so operate on the cell text, not raw HTML.
    raw = ""
    for cell in doc.xpath(
        '//tr[th[contains(text(),"Best Sellers Rank")]]/td//text()'
        + " | //li[span[contains(text(),'Best Sellers Rank')]]/span[last()]//text()"
    ):
        cleaned = _text(cell)
        if cleaned:
            raw += " " + cleaned
    match = re.search(r"#\s*([\d,]+)\s*in\s+([^()\n]+)", raw)
    if match:
        return _to_int(match.group(1).replace(",", "")), _text(match.group(2))
    # Fallback: some pages keep label + value in one text node.
    match = re.search(
        r"Best Sellers Rank[:\s#]*([\d,]+)\s*in\s+([^()\n]+)",
        html_text,
        re.IGNORECASE,
    )
    if match:
        return _to_int(match.group(1).replace(",", "")), _text(match.group(2))
    return 0, ""


def _amazon_offer_count(html_text: str) -> int:
    match = re.search(r"New\s*\((\d+)\)", html_text)
    return _to_int(match.group(1) if match else None)


def _amazon_badges(doc: Any) -> list[str]:
    badges: list[str] = []
    for raw in doc.xpath('//span[contains(@class,"a-badge-text")]//text()'):
        cleaned = _text(raw)
        if cleaned and cleaned not in badges:
            badges.append(cleaned)
    if not badges and re.search(
        r"Amazon's Choice|Amazon&nbsp;s Choice", str(doc.text_content()), re.IGNORECASE
    ):
        badges.append("Amazon's Choice")
    return badges


def _amazon_category(doc: Any, bsr_category: str) -> str:
    if bsr_category:
        return bsr_category
    crumb = doc.xpath('//div[@id="wayfinding-breadcrumbs_feature_div"]//li[last()]//a//text()')
    return _text(_first_text(crumb))


def _parse_product_page(html_text: str, asin: str) -> dict[str, Any]:
    """Parse an Amazon product page into the normalized schema."""
    doc = _lxml_doc(html_text)
    if doc is None:
        return {}
    price, currency = _amazon_price(doc)
    rating = _amazon_rating(doc)
    review_count = _amazon_review_count(doc)
    bsr, bsr_category = _amazon_bsr_category(doc, html_text)

    buy_box = _text(_first_text(doc.xpath('//span[@id="sellerProfileTriggerId"]/text()')))
    if not buy_box:
        buy_box = _text(
            _first_text(doc.xpath('//div[@id="merchantInfoFeature_feature_div"]//text()'))
        )
        if buy_box.lower().startswith("sold by"):
            buy_box = _text(buy_box[7:])

    brand_raw = _text(_first_text(doc.xpath('//a[@id="bylineInfo"]//text()')))
    if brand_raw.lower().startswith("visit the"):
        brand = _text(brand_raw[9:])
        if brand.lower().endswith(" store"):
            brand = _text(brand[: -len(" store")])
    else:
        brand = brand_raw

    title = _text(_first_text(doc.xpath('//span[@id="productTitle"]/text()')))

    return {
        "asin": asin,
        "title": title,
        "price": price,
        "currency": currency,
        "buy_box": buy_box,
        "brand": brand,
        "rating": rating,
        "review_count": review_count,
        "bsr": bsr,
        "category": _amazon_category(doc, bsr_category),
        "offers": _amazon_offer_count(html_text),
        "url": f"{AMAZON_BASE}/dp/{asin}",
        # Badges are intentionally not part of the schema — they are exposed
        # here for consumers that opt in (e.g. the MCP tool description).
        "_badges": _amazon_badges(doc),
    }


def _item_from_search(node: Any) -> dict[str, Any]:
    """Normalize one search-result node into the schema (sparse defaults)."""
    asin = _text(node.get("data-asin") or "")
    if not asin:
        return {}
    title_raw = node.xpath(".//h2//span/text()") or node.xpath(".//h2//a/text()")
    title = _text(_first_text(title_raw))
    price, currency = 0.0, ""
    for raw in node.xpath(
        './/span[contains(@class,"a-price")]//span[contains(@class,"a-offscreen")]/text()'
    ):
        amount, curr = _price_parts(raw)
        if amount > 0:
            price, currency = amount, curr
            break
    rating_raw = _first_text(node.xpath('.//span[contains(@class,"a-icon-alt")]/text()'))
    match = re.search(r"([\d.]+)", rating_raw)
    rating = _to_float(match.group(1) if match else None)
    review_raw = _first_text(node.xpath('.//span[contains(@class,"s-underline-text")]/text()'))
    review_match = re.search(r"([\d,]+)", review_raw)
    review_count = _to_int(review_match.group(1).replace(",", "") if review_match else None)
    href = _first_text(node.xpath(".//h2//a/@href"))
    url = ""
    if href:
        if href.startswith("http"):
            url = href
        elif href.startswith("/"):
            url = f"{AMAZON_BASE}{href}"
    return {
        "asin": asin,
        "title": title,
        "price": price,
        "currency": currency,
        "buy_box": "",
        "brand": "",
        "rating": rating,
        "review_count": review_count,
        "bsr": 0,
        "category": "",
        "offers": 0,
        "url": url,
    }


async def get_product(asin: str) -> dict[str, Any]:
    """Fetch + normalize one Amazon product; {} on any failure (never raises)."""
    asin = (asin or "").strip().upper()
    if not _valid_asin(asin):
        logger.warning("amazon_invalid_asin", extra={"asin": asin})
        return {}
    url = f"{AMAZON_BASE}/dp/{asin}"

    try:
        if not await _robots_allowed(url):
            logger.info("amazon_robots_blocked", extra={"url": url})
            return {}
        html_text = await _fetch_html(url)
        if html_text and not _is_amazon_block(html_text, 200):
            product = _parse_product_page(html_text, asin)
            if product.get("title"):
                return product
        # Scrape failed or blocked → optional Rainforest free-tier fallback.
        rainforest = await _amazon_via_rainforest(url)
        if isinstance(rainforest, dict) and isinstance(rainforest.get("product"), dict):
            return _from_rainforest(asin, rainforest["product"])
        return {}
    except Exception as exc:  # noqa: BLE001 - outermost safety net for a never-raise API
        logger.warning(
            "amazon_get_product_failed",
            extra={"asin": asin, "error": str(exc)[:160]},
        )
        return {}


def _from_rainforest(asin: str, product: dict[str, Any]) -> dict[str, Any]:
    """Normalize a Rainforest ``product`` payload into the schema."""
    price_raw = (
        product.get("buybox_winner", {}).get("price")
        or product.get("price")
        or product.get("prices", {}).get("current")
        or 0
    )
    price, currency = (
        _price_parts(str(price_raw))
        if not isinstance(price_raw, (int, float))
        else (float(price_raw), "USD")
    )
    ratings_total = product.get("ratings_total") or product.get("rating_total") or 0
    rating = product.get("rating") or 0.0
    buy_box = product.get("buybox_winner", {}).get("name") or ""
    return {
        "asin": asin,
        "title": _text(product.get("title")),
        "price": price,
        "currency": currency or "USD",
        "buy_box": _text(buy_box),
        "brand": _text(product.get("brand")),
        "rating": _to_float(rating),
        "review_count": _to_int(ratings_total),
        "bsr": _to_int(product.get("best_sellers_rank") or product.get("bsr")),
        "category": _text(product.get("category_path") or product.get("category")),
        "offers": _to_int(product.get("offers") or product.get("offer_count")),
        "url": _text(product.get("link") or f"{AMAZON_BASE}/dp/{asin}"),
    }


async def search_products(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search Amazon and return up to ``limit`` normalized products (never raises)."""
    query = (query or "").strip()
    if not query:
        return []
    try:
        cap = max(1, min(int(limit), 100))
    except (TypeError, ValueError):
        cap = 20
    url = f"{AMAZON_BASE}/s"
    try:
        if not await _robots_allowed(url):
            return []
        html_text = await _fetch_html(url, params={"k": query})
        if not html_text or _is_amazon_block(html_text, 200):
            return []
        doc = _lxml_doc(html_text)
        if doc is None:
            return []
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for node in doc.xpath('//div[@data-component-type="s-search-result"]'):
            item = _item_from_search(node)
            if not item:
                continue
            if item["asin"] in seen:
                continue
            seen.add(item["asin"])
            results.append(item)
            if len(results) >= cap:
                break
        return results
    except Exception as exc:  # noqa: BLE001 - outermost safety net for a never-raise API
        logger.warning(
            "amazon_search_failed",
            extra={"query": query[:80], "error": str(exc)[:160]},
        )
        return []
