# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Emitter payloads (commerce half) for the 2026-10-23 schema alignment.

Every shape below is what the handler writes, copied from the normalizers
(``_parse_product_page`` / ``_from_rainforest`` / ``_normalize_search_item`` /
``_from_render_json`` / app-store and grants/drops normalizers), never from the
``outputSchema`` it is checked against. That is what makes the assertion a
contract rather than an echo.
"""

from __future__ import annotations

from typing import Any

AMAZON_PRODUCT: dict[str, Any] = {
    "asin": "B08N5WRWNW",
    "title": "Echo Dot (4th Gen) Smart speaker with Alexa",
    "price": 49.99,
    "currency": "USD",
    "buy_box": "Amazon.com",
    "brand": "Amazon",
    "rating": 4.7,
    "review_count": 15234,
    "bsr": 12,
    "category": "Electronics",
    "offers": 3,
    "url": "https://www.amazon.com/dp/B08N5WRWNW",
}
WALMART_PRODUCT: dict[str, Any] = {
    "product_id": "4JH7P89H7X5P",
    "title": 'onn. 32" Class HD LED Roku Smart TV',
    "price": 98.0,
    "currency": "USD",
    "seller": "Walmart.com",
    "rating": 4.3,
    "stock": True,
    "url": "https://www.walmart.com/ip/4JH7P89H7X5P",
}

COMMERCE_PAYLOADS: dict[str, Any] = {
    "pry_amazon_product": AMAZON_PRODUCT,
    "pry_amazon_search": [AMAZON_PRODUCT],
    "pry_walmart_product": WALMART_PRODUCT,
    "pry_tiktok_trending": [
        {
            "product_id": "1729400000000000000",
            "title": "Portable Blender 350ml",
            "price": 12.99,
            "sold_count": 4200,
            "gmv_estimate": 54558.0,
            "rating": 4.6,
            "shop": "Trendy Finds",
            "url": "https://shop.tiktok.com/view/product/1729400000000000000",
        }
    ],
    "pry_app_search": [
        {
            "app_id": 886427876,
            "title": "Coinbase: Buy Bitcoin & ETH",
            "developer": "Coinbase",
            "genre": "Finance",
            "rating": 4.7,
            "rating_count": 1000000,
            "price": "Free",
            "version": "12.5",
            "url": "https://apps.apple.com/us/app/id886427876",
        }
    ],
    "pry_app_reviews": [
        {
            "author": "alice",
            "rating": 5,
            "title": "Solid",
            "body": "Fast and clear.",
            "date": "2026-10-01T09:12:00-07:00",
            "version": "12.5",
        }
    ],
    "pry_grants": [
        {
            "id": "NSF-2612345",
            "title": "SBIR Phase I: Retrieval Tooling",
            "agency": "NSF",
            "funding_type": "Grant",
            "open_date": "2026-09-01",
            "close_date": "2026-11-01",
            "amount": "$250,000",
            "eligible": "Small businesses",
            "url": "https://www.grants.gov/search-results-detail/2612345",
            "source": "grants.gov",
        }
    ],
    "pry_drop_alert": [
        {
            "alert_id": "drop_1",
            "product": "RTX 5090",
            "current_price": 1999.0,
            "target_price": 1799.0,
            "triggered": False,
            "delta_pct": 11.1,
        }
    ],
}
