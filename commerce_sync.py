import httpx
"""Pry — Commerce Platform Sync Engine.
Unified interface for WooCommerce, Shopify, and generic API sync."""
from paths import PRY_DATA_DIR

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Record sync operation ──

COMMERCE_DIR = PRY_DATA_DIR / "commerce"
COMMERCE_DIR.mkdir(parents=True, exist_ok=True)


async def sync_to_woocommerce(
    products: list[dict[str, Any]],
    wp_url: str,
    consumer_key: str,
    consumer_secret: str,
    category_id: int = 0,
    status: str = "draft",
) -> dict[str, Any]:
    """Sync products to WooCommerce via REST API.

    Args:
        products: List of product dicts with name, price, description, image_url
        wp_url: WordPress site URL (e.g., https://mystore.com)
        consumer_key: WooCommerce REST API consumer key
        consumer_secret: WooCommerce REST API consumer secret
        category_id: Product category ID to assign
        status: Product status (draft, publish, pending)
    """
    from client import get_client

    client = await get_client()
    base_url = wp_url.rstrip("/")
    auth = (consumer_key, consumer_secret)

    results = []
    for product in products:
        wc_product = {
            "name": product.get("name", "Unnamed Product")[:255],
            "regular_price": str(product.get("price", 0)),
            "description": (product.get("description") or product.get("content", ""))[:5000],
            "short_description": (product.get("short_description") or "")[:500],
            "images": [{"src": product["image_url"]}] if product.get("image_url") else [],
            "categories": [{"id": category_id}] if category_id else [],
            "status": status,
            "meta_data": [
                {"key": "_pry_source_url", "value": product.get("url", "")},
                {
                    "key": "_pry_imported_at",
                    "value": __import__("datetime")
                    .datetime.now(__import__("datetime").timezone.utc)
                    .isoformat(),
                },
            ],
        }

        try:
            resp = await client.post(
                f"{base_url}/wp-json/wc/v3/products",
                json=wc_product,
                auth=auth,
                timeout=30,
            )
            if resp.is_success:
                data = resp.json()
                results.append(
                    {
                        "success": True,
                        "woo_id": data.get("id"),
                        "name": data.get("name"),
                        "edit_url": f"{base_url}/wp-admin/post.php?post={data.get('id')}&action=edit",
                    }
                )
            else:
                results.append(
                    {
                        "success": False,
                        "name": product.get("name", "Unknown"),
                        "error": f"WooCommerce error {resp.status_code}: {resp.text[:200]}",
                    }
                )
        except (httpx.HTTPError, httpx.RequestError) as e:
            results.append(
                {
                    "success": False,
                    "name": product.get("name", "Unknown"),
                    "error": str(e)[:200],
                }
            )

    success_count = sum(1 for r in results if r["success"])
    return {
        "success": success_count > 0,
        "total": len(products),
        "synced": success_count,
        "failed": len(products) - success_count,
        "results": results,
    }


async def sync_to_shopify(
    products: list[dict[str, Any]],
    shop_url: str,
    access_token: str,
) -> dict[str, Any]:
    """Sync products to Shopify via REST API.

    Args:
        products: List of product dicts with name, price, description, image_url
        shop_url: Shopify store URL (e.g., https://mystore.myshopify.com)
        access_token: Shopify admin API access token
    """
    from client import get_client

    client = await get_client()
    base_url = shop_url.rstrip("/")

    results = []
    for product in products:
        shopify_product = {
            "product": {
                "title": (product.get("name") or "Unnamed Product")[:255],
                "body_html": f"<div>{(product.get('description') or product.get('content', ''))[:5000]}</div>",
                "vendor": "Pry Import",
                "product_type": "Reference",
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

        try:
            resp = await client.post(
                f"{base_url}/admin/api/2024-01/products.json",
                json=shopify_product,
                headers={"X-Shopify-Access-Token": access_token},
                timeout=30,
            )
            if resp.is_success:
                data = resp.json()
                pid = data.get("product", {}).get("id")
                results.append(
                    {
                        "success": True,
                        "shopify_id": pid,
                        "name": data.get("product", {}).get("title"),
                        "edit_url": f"{base_url}/admin/products/{pid}",
                    }
                )
            else:
                results.append(
                    {
                        "success": False,
                        "name": product.get("name", "Unknown"),
                        "error": f"Shopify error {resp.status_code}: {resp.text[:200]}",
                    }
                )
        except (httpx.HTTPError, httpx.RequestError) as e:
            results.append(
                {
                    "success": False,
                    "name": product.get("name", "Unknown"),
                    "error": str(e)[:200],
                }
            )

    success_count = sum(1 for r in results if r["success"])
    return {
        "success": success_count > 0,
        "total": len(products),
        "synced": success_count,
        "failed": len(products) - success_count,
        "results": results,
    }
