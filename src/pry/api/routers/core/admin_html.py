"""Server-rendered admin HTML dashboard."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import Query
from fastapi.responses import HTMLResponse

from pry.api.routers.core.admin import router
from pry.api.routers.core.admin_shared import (
    _compute_profits,
    _earnings_source,
    _fmt_usd,
    _get_apify_profits,
    _get_x402_payments,
    _parse_ts,
)
from pry.core.deps import automator, cache, ratelimiter

logger = logging.getLogger(__name__)


@router.get("/v1/admin", summary="Admin HTML dashboard", response_class=HTMLResponse)
async def admin_html_dashboard(
    days: int = Query(30, description="Number of days to look back"),
) -> HTMLResponse:
    """Server-rendered admin dashboard (pryscraper.com visual language)."""
    d = _gather_dashboard_data(days)
    profits = d["profits"]
    apify = d["apify"]
    cache_stats = d["cache_stats"]
    rate_stats = d["rate_stats"]
    total_earnings = d["total_earnings"]
    mrr = d["mrr"]
    growth = d["growth"]
    backend = d["backend"]
    top_payers = d["top_payers"]
    networks = d["networks"]
    recent = d["recent"]

    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    net = profits["x402"]["net_profit_usd"]
    growth_pct = growth.get("growth_pct", 0) if isinstance(growth, dict) else 0

    network_rows = _network_rows(networks)
    treasury_rows = _treasury_rows(d["treasury"])
    recent_rows = _recent_rows(recent)
    payer_rows = _payer_rows(top_payers, d.get("analytics_error"))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pry — Admin</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,system-ui,sans-serif; background:#070b13; color:#e2e8f0; padding:2rem; }}
a {{ color:#38bdf8; text-decoration:none; }}
a:hover {{ text-decoration:underline; }}
header {{ display:flex; align-items:center; gap:.75rem; margin-bottom:.25rem; }}
header img {{ height:34px; }}
h1 {{ font-size:1.4rem; color:#c8f04b; letter-spacing:.02em; }}
.subtitle {{ color:#64748b; margin-bottom:2rem; font-size:.85rem; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:1rem; margin-bottom:1.5rem; }}
.card {{ background:rgba(255,255,255,.03); border:1px solid rgba(200,240,75,.12); border-radius:14px; padding:1.25rem; backdrop-filter:blur(8px); }}
.card h3 {{ font-size:.7rem; text-transform:uppercase; letter-spacing:.08em; color:#64748b; margin-bottom:.5rem; }}
.card .value {{ font-size:1.7rem; font-weight:700; color:#f8fafc; }}
.card .sub {{ font-size:.78rem; color:#64748b; margin-top:.3rem; }}
.lime {{ color:#c8f04b; }} .cyan {{ color:#38bdf8; }} .pos {{ color:#4ade80; }} .neg {{ color:#f87171; }} .muted {{ color:#64748b; }}
.section {{ margin-bottom:2rem; }}
.section h2 {{ font-size:1rem; color:#c8f04b; margin-bottom:.75rem; }}
.panel {{ background:rgba(255,255,255,.03); border:1px solid rgba(56,189,248,.12); border-radius:14px; padding:1rem; overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; font-size:.82rem; }}
th,td {{ padding:.5rem .6rem; text-align:left; border-bottom:1px solid rgba(255,255,255,.06); }}
th {{ color:#64748b; font-weight:600; text-transform:uppercase; font-size:.65rem; letter-spacing:.06em; }}
.badge {{ display:inline-block; padding:2px 8px; border-radius:999px; font-size:.68rem; font-weight:600; }}
.badge-ok {{ background:rgba(74,222,128,.12); color:#4ade80; }}
.badge-err {{ background:rgba(248,113,113,.12); color:#f87171; }}
.empty {{ text-align:center; color:#475569; }}
footer {{ margin-top:2rem; font-size:.72rem; color:#475569; }}
</style>
</head>
<body>
<header><img src="https://pryscraper.com/favicon.svg" alt="PRY" onerror="this.style.display='none'"><h1>Pry Admin</h1></header>
<p class="subtitle">Self-hosted monitoring · earnings backend: {backend} · {now}</p>

<div class="grid">
  <div class="card"><h3>Total Earnings ({days}d)</h3><div class="value lime">{_fmt_usd(total_earnings.get("total_usd", 0))}</div><div class="sub">{sum(total_earnings.get("counts", {}).values())} events</div></div>
  <div class="card"><h3>x402 Revenue</h3><div class="value">{_fmt_usd(profits["x402"]["revenue_usd"])}</div><div class="sub">{profits["x402"]["payment_count"]} payments</div></div>
  <div class="card"><h3>MRR</h3><div class="value cyan">{_fmt_usd(mrr.get("mrr_usd", 0))}</div><div class="sub">subscriptions</div></div>
  <div class="card"><h3>Growth</h3><div class="value {"pos" if growth_pct >= 0 else "neg"}">{growth_pct:+.1f}%</div><div class="sub">vs previous {days}d</div></div>
  <div class="card"><h3>Net Profit</h3><div class="value {"pos" if net >= 0 else "neg"}">{_fmt_usd(net)}</div><div class="sub">after 2% fees + costs</div></div>
  <div class="card"><h3>Operating Cost</h3><div class="value neg">{_fmt_usd(profits["costs"]["total_operating_cost_usd"])}</div><div class="sub">{_fmt_usd(profits["costs"]["projected_monthly_usd"])}/mo projected</div></div>
</div>

<div class="grid">
  <div class="card"><h3>Cache Hit Rate</h3><div class="value">{cache_stats.get("hit_rate", 0):.1f}%</div><div class="sub">{cache_stats.get("hits", 0)} hits</div></div>
  <div class="card"><h3>Requests</h3><div class="value">{rate_stats.get("total_requests", 0)}</div><div class="sub">{rate_stats.get("active_ips", 0)} active IPs</div></div>
  <div class="card"><h3>Blocked</h3><div class="value neg">{rate_stats.get("total_blocked", 0)}</div><div class="sub">rate-limited</div></div>
  <div class="card"><h3>Sessions</h3><div class="value">{len(automator.sessions)}</div><div class="sub">browser sessions</div></div>
</div>

<div class="grid">
  <div class="section"><h2>Top Payers</h2><div class="panel"><table><tr><th>Payer</th><th>Total</th></tr>{payer_rows}</table></div></div>
  <div class="section"><h2>Network Breakdown</h2><div class="panel"><table><tr><th>Network</th><th>Count</th><th>Volume</th></tr>{network_rows}</table></div></div>
</div>

<div class="section"><h2>Treasury Balances</h2><div class="panel"><table><tr><th>Chain</th><th>Balance</th><th>Address</th></tr>{treasury_rows}</table></div></div>

<div class="section"><h2>Recent Payments</h2><div class="panel"><table><tr><th>Time</th><th>Network</th><th>Asset</th><th>Amount</th><th>Status</th></tr>{recent_rows}</table></div></div>

<div class="section"><h2>System Health</h2><div class="panel"><table>
<tr><th>Component</th><th>Status</th><th>Details</th></tr>
<tr><td>Cache</td><td><span class="badge {"badge-ok" if cache_stats.get("hit_rate", 0) > 30 else "badge-err"}">{"OK" if cache_stats.get("hit_rate", 0) > 30 else "Low"}</span></td><td>{cache_stats.get("hit_rate", 0):.1f}% hit rate, {cache_stats.get("size", 0)} entries</td></tr>
<tr><td>Automator</td><td><span class="badge {"badge-ok" if automator.available else "badge-err"}">{"Available" if automator.available else "Unavailable"}</span></td><td>{len(automator.sessions)} active sessions</td></tr>
<tr><td>Apify</td><td><span class="badge {"badge-ok" if apify.get("configured") else "badge-err"}">{"Configured" if apify.get("configured") else "Not configured"}</span></td><td>{apify.get("total_runs", 0)} runs · {_fmt_usd(apify.get("total_profit_usd", 0))}</td></tr>
<tr><td>Prometheus</td><td><span class="badge badge-ok">Active</span></td><td><a href="/v1/admin/metrics">/v1/admin/metrics</a> for Grafana</td></tr>
</table></div></div>

<footer>Pry v3.0.0 · <a href="/v1/admin/earnings">earnings API</a> · <a href="/v1/admin/payments/recent">recent payments</a> · <a href="/v1/admin/payments/failed">failed</a> · <a href="/v1/admin/users">users</a></footer>
</body>
</html>"""
    return HTMLResponse(content=html)


# ── Private helpers (extracted from admin_html_dashboard — audit P2) ────────


def _gather_dashboard_data(days: int) -> dict[str, Any]:
    """Collect every dashboard data source, degrading instead of 500ing."""
    profits = _compute_profits(days)
    apify = _get_apify_profits()
    cache_stats = cache.stats()
    rate_stats = ratelimiter.get_stats()

    # Earnings (tracker with analytics fallback)
    try:
        tracker, backend = _earnings_source()
        total_earnings = tracker.get_total_earnings(days)
        mrr = tracker.get_mrr()
        growth = tracker.get_growth_rate(days)
        treasury = tracker.get_treasury_balances()
    except Exception as e:  # noqa: BLE001 - dashboard must never 500
        logger.warning("dashboard_earnings_failed", extra={"error": str(e)})
        total_earnings = {"total_usd": 0, "by_stream": {}, "counts": {}}
        mrr = {"mrr_usd": 0}
        growth = {"growth_pct": 0}
        treasury = {}
        backend = "unavailable"

    # Top payers + network breakdown + recent payments (analytics over payments.jsonl)
    analytics_error: str | None = None
    try:
        from pry.payments.analytics import get_analytics

        analytics = get_analytics()
        top_payers = analytics.get_top_payers(10)
        networks = analytics.get_network_breakdown(days)
    except Exception as e:  # noqa: BLE001 - dashboard must never 500
        analytics_error = str(e)
        logger.warning("dashboard_analytics_failed", extra={"error": analytics_error})
        top_payers, networks = [], {}
    recent = _get_x402_payments(days=days)
    recent.sort(
        key=lambda p: _parse_ts(p.get("ts", "")) or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    recent = recent[:15]

    return {
        "profits": profits,
        "apify": apify,
        "cache_stats": cache_stats,
        "rate_stats": rate_stats,
        "total_earnings": total_earnings,
        "mrr": mrr,
        "growth": growth,
        "treasury": treasury,
        "backend": backend,
        "top_payers": top_payers,
        "networks": networks,
        "recent": recent,
        "analytics_error": analytics_error,
    }


def _network_rows(networks: dict) -> str:
    return (
        "".join(
            f"<tr><td>{n}</td><td>{d.get('count', 0)}</td><td>{_fmt_usd(d.get('total_usd', 0))}</td></tr>"
            for n, d in networks.items()
        )
        or "<tr><td colspan='3' class='empty'>No payments yet</td></tr>"
    )


def _treasury_rows(treasury: dict) -> str:
    return (
        "".join(
            f"<tr><td>{chain.upper()}</td><td>{_fmt_usd(b.get('balance_usd', b.get('total_usd', 0)))}</td>"
            f"<td class='muted'>{b.get('address', b.get('wallet', '') or '—')}</td></tr>"
            for chain, b in treasury.items()
            if isinstance(b, dict)
        )
        or "<tr><td colspan='3' class='empty'>Treasury not configured</td></tr>"
    )


def _recent_rows(recent: list) -> str:
    return (
        "".join(
            f"<tr><td class='muted'>{(p.get('ts', '') or '')[:19]}</td>"
            f"<td>{p.get('network', '?')}</td><td>{p.get('asset', '?')}</td>"
            f"<td>{_fmt_usd(p.get('amount_usd', 0))}</td>"
            f"<td><span class='badge {'badge-ok' if p.get('verified') else 'badge-err'}'>"
            f"{'verified' if p.get('verified') else 'failed'}</span></td></tr>"
            for p in recent
        )
        or "<tr><td colspan='5' class='empty'>No payments yet</td></tr>"
    )


def _payer_rows(top_payers: list, analytics_error: str | None = None) -> str:
    if analytics_error:
        return "<tr><td colspan='2' class='empty'>Unavailable — analytics error</td></tr>"
    return (
        "".join(
            f"<tr><td>{p['payer']}</td><td>{_fmt_usd(p['total_usd'])}</td></tr>" for p in top_payers
        )
        or "<tr><td colspan='2' class='empty'>No payers yet</td></tr>"
    )
