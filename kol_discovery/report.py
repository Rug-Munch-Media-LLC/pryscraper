"""Markdown report rendering from a saved registry."""

from __future__ import annotations

from typing import Any

from .risk import band


def _table_header() -> list[str]:
    return [
        "| # | handle | platform | followers | risk | band | declared wallets | telegram |",
        "|---|--------|----------|-----------|------|------|------------------|----------|",
    ]


def top_risk(accounts: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    ranked = sorted(accounts, key=lambda row: float(row.get("risk_score") or 0), reverse=True)
    return ranked[:limit]


def render_sources(sources: list[dict[str, Any]]) -> list[str]:
    lines = ["## Sources", "", "| source | url | status | evidence |", "|---|---|---|---|"]
    for row in sources:
        detail = str(row.get("detail", "")).replace("|", "/")
        lines.append(
            f"| {row.get('name')} | {row.get('url')} | {row.get('status')} "
            f"({row.get('http_status')}) | {detail} |"
        )
    return lines


def render_report(registry: dict[str, Any], limit: int = 10) -> str:
    """Render the whole discovery report. Pure — no I/O."""
    stats = registry.get("stats", {})
    accounts = registry.get("accounts", [])
    lines = [
        "# KOL discovery report",
        "",
        f"schema: `{registry.get('schema_version')}`",
        "",
        "## Counts",
        "",
        f"- accounts: **{stats.get('accounts', 0)}** {stats.get('by_platform', {})}",
        f"- wallets declared: **{stats.get('wallets_declared', 0)}**",
        f"- wallets inferred (never presented as fact): **{stats.get('wallets_inferred', 0)}**",
        f"- accounts with a telegram hand-off: **{stats.get('with_telegram', 0)}**",
        "",
        *render_sources(registry.get("sources", [])),
        "",
        "## Top risk accounts",
        "",
        *_table_header(),
    ]
    for index, row in enumerate(top_risk(accounts, limit), start=1):
        wallets = [
            w["address"][:6] + "…"
            for w in row.get("wallets", [])
            if w.get("attribution") != "inferred"
        ]
        lines.append(
            f"| {index} | @{row.get('handle')} | {row.get('platform')} | {row.get('followers')} "
            f"| {row.get('risk_score')} | {band(float(row.get('risk_score') or 0))} "
            f"| {', '.join(wallets) or '—'} | {row.get('telegram') or '—'} |"
        )
    if not accounts:
        lines.append("")
        lines.append("_No accounts ingested — every source was blocked or offline._")
    return "\n".join(lines) + "\n"
