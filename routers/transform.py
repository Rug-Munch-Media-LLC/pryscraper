"""Pry — Transform router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Body

from deps import scraper
from errors import InvalidRequestError, ScrapeError
from pryextras import TransformEngine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Transform"])

@router.post("/v1/transform", tags=["Transform"], summary="Transform data to multiple formats")
async def transform_data(
    data: list[dict[str, Any]] = Body(...), format: str = "csv"
) -> dict[str, Any]:
    te = TransformEngine()
    if format == "csv":
        result = te.to_csv(data)
    elif format == "sql":
        result = "\n".join(te.to_sql(row) for row in data)
    elif format == "html":
        result = te.to_html_table(data)
    elif format == "markdown":
        result = te.to_markdown_table(data)
    else:
        raise InvalidRequestError(f"Unknown format: {format}")
    return {"success": True, "data": {"output": result, "format": format}}


@router.post("/v1/pipe", tags=["Transform"], summary="Scrape and transform via data pipeline")
async def data_pipeline(data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    url = data.get("url", "")
    transform = data.get("transform", "json")
    result = await scraper.scrape(url, {"bypass_cloudflare": True})
    if result.get("status") != "ok":
        raise ScrapeError(result.get("error") or "Pipeline failed")
    content = result.get("content", "")
    title = result.get("title", url)
    if transform == "sql":
        from pryextras import TransformEngine

        te = TransformEngine()
        output = te.to_sql({"url": url, "title": title, "content": content[:50000]})
    elif transform == "csv":
        import csv
        import io

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["url", "title", "content"])
        w.writerow([url, title, content[:50000]])
        output = buf.getvalue()
    else:
        output = json.dumps({"url": url, "title": title, "content": content[:100000]}, indent=2)
    return {"success": True, "data": {"url": url, "output": output, "format": transform}}
