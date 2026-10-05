"""Pry — Commerce Platform Sync Engine.
Unified interface for WooCommerce, Shopify, and generic API sync."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
import logging
from typing import Any

import httpx

from pry.commerce.commerce_sync_push import push_product, summarize
from pry.core.paths import PRY_DATA_DIR

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
    from pry.api.client import get_client

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
    access_token: str = "",
    *,
    code: str = "",
    shop_domain: str = "",
    api_key: str = "",
    api_secret: str = "",
) -> dict[str, Any]:
    """Sync products to Shopify via REST API.

    Two auth modes are supported:

    1. Static access token (server-to-server, classic custom apps):
         await sync_to_shopify(products, shop_url, access_token="shpat_...")
    2. OAuth code exchange (public apps, embedded installs):
         await sync_to_shopify(
             products,
             shop_url,
             code="<oauth callback code>",
             shop_domain="mystore.myshopify.com",
             api_key="...",
             api_secret="...",
         )
       The code is exchanged for a permanent access token via
       ``shopify_oauth.exchange_code`` and then the sync proceeds normally.

    Args:
        products: List of product dicts with name, price, description, image_url
        shop_url: Shopify store URL (e.g., https://mystore.myshopify.com)
        access_token: Shopify admin API access token (static mode)
        code: OAuth callback code (public-app mode)
        shop_domain: Bare *.myshopify.com domain (public-app mode)
        api_key: Public app API key (public-app mode)
        api_secret: Public app API secret (public-app mode)

    Raises:
        ValueError: if neither a static access_token nor a code-flow tuple
            is provided.
    """
    from pry.api.client import get_client
    from pry.commerce.shopify_oauth import exchange_code

    if not access_token:
        if not (code and shop_domain and api_key and api_secret):
            logger.error(
                "shopify_sync_missing_credentials",
                extra={"shop_url": shop_url, "has_code": bool(code)},
            )
            return {
                "success": False,
                "total": len(products),
                "synced": 0,
                "failed": len(products),
                "results": [],
                "error": "missing credentials: provide access_token OR (code, shop_domain, api_key, api_secret)",
            }
        token_resp = exchange_code(shop_domain, code, api_key, api_secret)
        access_token = token_resp["access_token"]

    client = await get_client()
    base_url = shop_url.rstrip("/")

    results = []
    for product in products:
        await push_product(client, product, base_url, access_token, results)

    return summarize(len(products), results)
