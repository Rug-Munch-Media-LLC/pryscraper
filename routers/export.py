"""Pry — Export router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import html
import logging
from datetime import UTC
from typing import Any

from fastapi import APIRouter, Body

from pry.core.deps import scraper
from pry.core.errors import ScrapeError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Export"])


@router.post("/v1/export", tags=["Export"], summary="Export scraped content in multiple formats")
async def export_data(url: str = Body(...), format: str = "json") -> dict[str, Any]:
    """Export scraped content in multiple formats: json, csv, txt, rss.
    Firecrawl only does markdown."""
    result = await scraper.scrape(url)
    if result.get("status") != "ok":
        raise ScrapeError(result.get("error") or "Export failed")
    content = result.get("content", "")
    title = result.get("title", url)

    if format == "json":
        return {
            "success": True,
            "data": {"url": url, "title": title, "content": content, "format": "json"},
        }
    elif format == "csv":
        import csv
        import io

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["url", "title", "content"])
        w.writerow([url, title, content[:50000]])
        return {"success": True, "data": {"csv": buf.getvalue(), "format": "csv"}}
    elif format == "rss":
        from datetime import datetime

        safe_title = html.escape(title)
        safe_url = html.escape(url)
        rss = f"""<?xml version="1.0"?>
<rss version="2.0"><channel>
<title>Pry: {safe_title}</title>
<link>{safe_url}</link>
<description>Scraped content from {safe_url}</description>
<item><title>{safe_title}</title><link>{safe_url}</link>
<description><![CDATA[{content[:50000]}]]></description>
<pubDate>{datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S UTC")}</pubDate>
</item></channel></rss>"""
        return {"success": True, "data": {"rss": rss, "format": "rss"}}
    return {"success": True, "data": {"text": content[:100000], "format": "txt"}}
