"""Pry — Shopify product payload construction.

Pure builders that translate a Pry product dict into the Shopify REST
product envelope. Kept free of I/O so the mapping is unit-testable in
isolation."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from typing import Any

SHOPIFY_API_VERSION = "2024-01"
SHOPIFY_VENDOR = "Pry Import"
SHOPIFY_PRODUCT_TYPE = "Reference"


def build_shopify_payload(product: dict[str, Any]) -> dict[str, Any]:
    """Build the Shopify ``{"product": {...}}`` envelope for one product.

    Args:
        product: Pry product dict with name, price, description, image_url.

    Returns:
        The request body accepted by the Shopify products endpoint.
    """
    description = product.get("description") or product.get("content", "")
    return {
        "product": {
            "title": (product.get("name") or "Unnamed Product")[:255],
            "body_html": f"<div>{description[:5000]}</div>",
            "vendor": SHOPIFY_VENDOR,
            "product_type": SHOPIFY_PRODUCT_TYPE,
            "status": "draft",
            "variants": [
                {
                    "price": str(product.get("price", 0)),
                    "inventory_management": "shopify",
                }
            ],
            "metafields": [
                {
                    "key": "pry_source_url",
                    "value": product.get("url", ""),
                    "type": "single_line_text_field",
                    "namespace": "pry",
                }
            ],
        }
    }
