"""Pry — Shopify push execution.

Per-product HTTP push against the Shopify admin REST API plus the
result-normalisation pieces, so the orchestrator only sequences them."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from typing import Any

import httpx

from pry.commerce.commerce_sync_payload import SHOPIFY_API_VERSION, build_shopify_payload


def _error_result(product: dict[str, Any], error: str) -> dict[str, Any]:
    """Return a normalized failed-sync result for one product."""
    return {
        "success": False,
        "name": product.get("name", "Unknown"),
        "error": error[:200],
    }


def _apply_response(
    product: dict[str, Any],
    response: httpx.Response,
    base_url: str,
    results: list[dict[str, Any]],
) -> None:
    """Append the sync result for one HTTP response."""
    if response.is_success:
        data = response.json()
        shopify_product = data.get("product", {})
        pid = shopify_product.get("id")
        results.append(
            {
                "success": True,
                "shopify_id": pid,
                "name": shopify_product.get("title"),
                "edit_url": f"{base_url}/admin/products/{pid}",
            }
        )
    else:
        results.append(
            _error_result(
                product,
                f"Shopify error {response.status_code}: {response.text[:200]}",
            )
        )


async def push_product(
    client: httpx.AsyncClient,
    product: dict[str, Any],
    base_url: str,
    access_token: str,
    results: list[dict[str, Any]],
) -> None:
    """Push one product to Shopify and append its result to ``results``."""
    try:
        response = await client.post(
            f"{base_url}/admin/api/{SHOPIFY_API_VERSION}/products.json",
            json=build_shopify_payload(product),
            headers={"X-Shopify-Access-Token": access_token},
            timeout=30,
        )
        _apply_response(product, response, base_url, results)
    except (httpx.HTTPError, httpx.RequestError) as exc:
        results.append(_error_result(product, str(exc)))


def summarize(total: int, results: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap per-product results in the sync summary envelope."""
    success_count = sum(1 for r in results if r["success"])
    return {
        "success": success_count > 0,
        "total": total,
        "synced": success_count,
        "failed": total - success_count,
        "results": results,
    }
