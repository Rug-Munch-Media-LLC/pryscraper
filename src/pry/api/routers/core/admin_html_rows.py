"""HTML table-row rendering for the server-rendered admin dashboard.

Split out of ``admin_html.py`` so the markup helpers have one owner.
``admin_html`` re-exports every helper so existing import paths keep working.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

from pry.api.routers.core.admin_shared import _fmt_usd


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
