"""Pry — Share router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import html
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Body
from fastapi.responses import HTMLResponse

from deps import scraper

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Share"])

@router.post("/v1/share", tags=["Share"], summary="Share scraped content via link")
async def share_scrape(data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    url = data.get("url", "")
    result = await scraper.scrape(url, {"bypass_cloudflare": True})
    sid = uuid.uuid4().hex[:8]
    _shares[sid] = {
        "url": url,
        "title": result.get("title", url),
        "content": result.get("content", ""),
        "method": result.get("method"),
        "ts": datetime.now(UTC).isoformat(),
    }
    return {"success": True, "data": {"share_id": sid, "url": f"/share/{sid}"}}


@router.get("/share/{share_id}", tags=["Share"], summary="View shared content")
async def view_share(share_id: str) -> HTMLResponse:
    d = _shares.get(share_id)
    if not d:
        return HTMLResponse("<h1>Not found</h1><p>Share expired.</p>", 404)
    st, sc, su = html.escape(d["title"]), html.escape(d["content"][:100000]), html.escape(d["url"])
    return HTMLResponse(
        f'<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>{st} — Pry Share</title>'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<style>body{{font-family:-apple-system,system-ui,sans-serif;background:#09090b;color:#e4e4e7;padding:2rem;max-width:800px;margin:0 auto}}"
        f"h1{{font-size:1.5rem;color:#f59e0b}}.meta{{color:#52525b;font-size:.85rem;margin-bottom:2rem}}"
        f"pre{{background:#18181b;border:1px solid #27272a;border-radius:8px;padding:1.5rem;white-space:pre-wrap}}</style></head><body>"
        f'<h1>🔧 {st}</h1><p class="meta"><a href="{su}">{su}</a> · {d["method"]} · {d["ts"][:10]}</p>'
        f"<pre>{sc}</pre></body></html>"
    )


_shares: dict[str, dict[str, Any]] = {}
