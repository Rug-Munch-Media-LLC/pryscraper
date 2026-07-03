"""Pry — Dashboard router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from deps import automator, cache, ratelimiter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Dashboard"])

@router.get("/dashboard", tags=["Dashboard"], summary="Pry health and performance dashboard")
async def dashboard() -> HTMLResponse:
    cache_stats = cache.stats()
    rate_stats = ratelimiter.get_stats()
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pry — Dashboard</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,system-ui,sans-serif; background:#0a0a0b; color:#e4e4e7; padding:2rem; }}
h1 {{ font-size:1.5rem; color:#f59e0b; margin-bottom:.5rem; }}
p {{ color:#71717a; margin-bottom:2rem; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:1rem; margin-bottom:2rem; }}
.card {{ background:#18181b; border:1px solid #27272a; border-radius:8px; padding:1.25rem; }}
.card h3 {{ font-size:.75rem; text-transform:uppercase; color:#71717a; margin-bottom:.5rem; }}
.card .value {{ font-size:1.75rem; font-weight:700; color:#f4f4f5; }}
.card .sub {{ font-size:.8rem; color:#52525b; margin-top:.25rem; }}
.status-ok {{ color:#22c55e; }} .status-warn {{ color:#eab308; }} .status-err {{ color:#ef4444; }}
table {{ width:100%; border-collapse:collapse; font-size:.85rem; }}
th,td {{ padding:.5rem; text-align:left; border-bottom:1px solid #27272a; }}
th {{ color:#71717a; font-weight:600; text-transform:uppercase; font-size:.7rem; }}
</style></head><body>
<h1>🔧 Pry Dashboard</h1>
<p>Scrape engine health and performance metrics</p>
<div class="grid">
  <div class="card"><h3>Cache Hit Rate</h3><div class="value">{cache_stats.get("hit_rate", 0)}%</div><div class="sub">{cache_stats.get("hits", 0)} hits / {cache_stats.get("size", 0)} entries</div></div>
  <div class="card"><h3>Rate Limit</h3><div class="value">{rate_stats.get("total_requests", 0)}</div><div class="sub">{rate_stats.get("active_ips", 0)} active IPs</div></div>
  <div class="card"><h3>Blocked</h3><div class="value">{rate_stats.get("total_blocked", 0)}</div><div class="sub">requests blocked</div></div>
  <div class="card"><h3>Sessions</h3><div class="value">{len(automator.sessions)}</div><div class="sub">active browser sessions</div></div>
</div>
<table><tr><th>Endpoint</th><th>Method</th><th>Status</th></tr>
<tr><td>/v1/scrape</td><td>POST</td><td class="status-ok">✅ Active</td></tr>
<tr><td>/v1/crawl</td><td>POST</td><td class="status-ok">✅ Active</td></tr>
<tr><td>/v1/automate</td><td>POST</td><td class="status-ok">✅ Active</td></tr>
<tr><td>/v1/batch</td><td>POST</td><td class="status-ok">✅ Active</td></tr>
<tr><td>/v1/stream</td><td>WebSocket</td><td class="status-ok">✅ Active</td></tr>
<tr><td>/v1/run</td><td>POST</td><td class="status-ok">✅ Active</td></tr>
<tr><td>FlareSolverr</td><td>Proxy</td><td class="status-ok">✅ Connected</td></tr>
</table>
<p style="margin-top:2rem;font-size:.75rem;color:#52525b">Pry v3.0.0 — Generated {datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")}</p>
</body></html>"""
    return HTMLResponse(content=html)
