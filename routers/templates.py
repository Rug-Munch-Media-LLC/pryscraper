"""Pry — Templates router."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT.
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Body
from pydantic import BaseModel

from pry.commerce.template_engine import execute_template, get_template, list_templates
from pry.core.errors import InvalidRequestError, NotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Templates"])


class BatchItem(BaseModel):
    """A single template execution request within a batch."""

    template_id: str
    url: str
    options: dict[str, Any] | None = None


class BatchResponse(BaseModel):
    """Batch execution result."""

    success: bool = True
    data: dict[str, Any]


MAX_BATCH_SIZE = 20


@router.get("/v1/templates", summary="List all pre-built scraper templates")
async def list_templates_endpoint() -> dict[str, Any]:
    """List all available pre-built scraper templates.

    Templates are one-click extractors for popular websites:
    Amazon, Walmart, Target, Best Buy, LinkedIn, Indeed, GitHub, etc.
    """
    templates = list_templates()
    categories: dict[str, list[dict[str, Any]]] = {}
    for t in templates:
        cat = t.get("category", "general")
        categories.setdefault(cat, []).append(t)
    return {
        "success": True,
        "data": {"templates": templates, "categories": categories, "total": len(templates)},
    }


@router.get("/v1/templates/{template_id}", summary="Get a scraper template")
async def get_template_endpoint(template_id: str) -> dict[str, Any]:
    """Get a specific scraper template with full schema details."""
    template = get_template(template_id)
    if not template:
        raise NotFoundError(f"Template not found: {template_id}")
    return {"success": True, "data": template}


@router.post("/v1/templates/execute", summary="Execute a scraper template against a URL")
async def execute_template_endpoint(
    template_id: str = Body(...),
    url: str = Body(...),
) -> dict[str, Any]:
    """Execute a pre-built scraper template against any URL.

    Example: use "amazon_product" template with an Amazon product URL
    to get structured title, price, rating, description, etc.

    Templates auto-detect the page structure using pre-configured CSS selectors.
    """
    result = await execute_template(template_id, url)
    return result


@router.post("/v1/templates/batch", summary="Execute multiple templates/URLs in parallel")
async def batch_execute(body: list[BatchItem]) -> dict[str, Any]:
    """Execute multiple scraper templates against multiple URLs in parallel.

    Runs up to 20 template executions concurrently. Each result preserves the
    original template_id and url for correlation.
    """
    if len(body) > MAX_BATCH_SIZE:
        raise InvalidRequestError(f"Max {MAX_BATCH_SIZE} items per batch, got {len(body)}")

    async def run_item(item: BatchItem) -> dict[str, Any]:
        try:
            result = await execute_template(item.template_id, item.url, **(item.options or {}))
            return {
                "template_id": item.template_id,
                "url": item.url,
                "result": result,
            }
        except Exception as e:  # noqa: BLE001
            return {
                "template_id": item.template_id,
                "url": item.url,
                "error": {"code": "execution_failed", "message": str(e)},
            }

    results = await asyncio.gather(*[run_item(item) for item in body], return_exceptions=True)

    flat: list[dict[str, Any]] = []
    failed = 0
    for r in results:
        if isinstance(r, Exception):
            flat.append({"error": {"code": "execution_failed", "message": str(r)}})
            failed += 1
        else:
            if "error" in r:  # type: ignore[operator]  # r is dict[str, Any] | BaseException after isinstance narrowing
                failed += 1
            flat.append(r)  # type: ignore[arg-type]  # r is narrowed to dict[str, Any] by isinstance check above

    return {
        "success": True,
        "data": {
            "results": flat,
            "total": len(flat),
            "failed": failed,
        },
    }
