"""Pry — Share router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import html
import logging
import threading
import time
import uuid
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Body
from fastapi.responses import HTMLResponse

from pry.core.deps import scraper

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Share"])


@router.post("/v1/share", tags=["Share"], summary="Share scraped content via link")
async def share_scrape(data: dict[str, Any] = Body(...)) -> dict[str, Any]:
    url = data.get("url", "")
    result = await scraper.scrape(url, {"bypass_cloudflare": True})
    sid = uuid.uuid4().hex[:8]
    _store_share(
        sid,
        {
            "url": url,
            "title": result.get("title", url),
            "content": result.get("content", ""),
            "method": result.get("method"),
            "ts": datetime.now(UTC).isoformat(),
        },
    )
    return {"success": True, "data": {"share_id": sid, "url": f"/share/{sid}"}}


@router.get("/share/{share_id}", tags=["Share"], summary="View shared content")
async def view_share(share_id: str) -> HTMLResponse:
    d = _get_share(share_id)
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


# Shares are ephemeral links: 24h lifetime and a hard entry cap, so an
# unauthenticated POST loop cannot grow the dict without bound.
_SHARE_TTL_SECONDS = 24 * 60 * 60
_SHARES_MAX = 1000
_shares: OrderedDict[str, dict[str, Any]] = OrderedDict()
_shares_lock = threading.Lock()


def _expired(entry: dict[str, Any], now: float) -> bool:
    """True once a share is past its TTL."""
    return now - float(entry.get("_ts", 0.0)) >= _SHARE_TTL_SECONDS


def _purge_expired(now: float | None = None) -> int:
    """Drop expired shares; returns how many were removed (caller holds lock)."""
    now = time.time() if now is None else now
    stale = [sid for sid, entry in _shares.items() if _expired(entry, now)]
    for sid in stale:
        del _shares[sid]
    return len(stale)


def _store_share(sid: str, entry: dict[str, Any]) -> None:
    """Insert a share, evicting expired entries then the oldest at the cap."""
    entry["_ts"] = time.time()
    with _shares_lock:
        _purge_expired(entry["_ts"])
        _shares[sid] = entry
        _shares.move_to_end(sid)
        while len(_shares) > _SHARES_MAX:
            _shares.popitem(last=False)


def _get_share(sid: str) -> dict[str, Any] | None:
    """Fetch a live share (LRU-refreshed); expired entries read as missing."""
    with _shares_lock:
        entry = _shares.get(sid)
        if entry is None:
            return None
        if _expired(entry, time.time()):
            del _shares[sid]
            return None
        _shares.move_to_end(sid)
        return entry
