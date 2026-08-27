"""Pry — Commerce router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body

from pry.core.errors import InvalidRequestError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Commerce"])


@router.post(
    "/v1/commerce/sync", tags=["Commerce"], summary="Sync products to WooCommerce or Shopify"
)
async def sync_commerce(
    platform: str = Body(...),
    products: list[dict[str, Any]] = Body(...),
    credentials: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Sync scraped products to your e-commerce platform.

    Platforms:
    - woocommerce: credentials = {"wp_url": "...", "consumer_key": "...", "consumer_secret": "..."}
    - shopify: credentials = {"shop_url": "...", "access_token": "..."}

    Products are imported as drafts for review before publishing.
    """
    from pry.commerce.commerce_sync import sync_to_shopify, sync_to_woocommerce

    if platform == "woocommerce":
        result = await sync_to_woocommerce(
            products=products,
            wp_url=credentials.get("wp_url", ""),
            consumer_key=credentials.get("consumer_key", ""),
            consumer_secret=credentials.get("consumer_secret", ""),
            category_id=credentials.get("category_id", 0),
            status=credentials.get("status", "draft"),
        )
    elif platform == "shopify":
        result = await sync_to_shopify(
            products=products,
            shop_url=credentials.get("shop_url", ""),
            access_token=credentials.get("access_token", ""),
        )
    else:
        raise InvalidRequestError(
            f"Unsupported platform: {platform}. Supported: woocommerce, shopify"
        )

    return {"success": result["success"], "data": result}


@router.get(
    "/v1/commerce/platforms", tags=["Commerce"], summary="List supported commerce platforms"
)
async def list_commerce_platforms() -> dict[str, Any]:
    """List supported e-commerce platforms and their credential requirements."""
    return {
        "success": True,
        "data": {
            "platforms": [
                {
                    "id": "woocommerce",
                    "name": "WooCommerce",
                    "credential_fields": [
                        "wp_url",
                        "consumer_key",
                        "consumer_secret",
                        "category_id",
                    ],
                    "product_fields": ["name", "price", "description", "image_url"],
                },
                {
                    "id": "shopify",
                    "name": "Shopify",
                    "credential_fields": ["shop_url", "access_token"],
                    "product_fields": ["name", "price", "description", "image_url"],
                },
            ]
        },
    }
