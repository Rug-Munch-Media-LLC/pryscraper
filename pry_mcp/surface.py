"""Pry — canonical MCP surface: four entries, a spend gate, a deadline bound.

Discovery in this server is expensive: a client pays for every tool schema it
loads, and most names differ only by a suffix. This module is the single place
that says which entry point owns a task, which calls spend money, and how a
search call behaves when its budget runs out.

The grouped index itself is built by ``pry_mcp.tools.help`` from ``PRY_TOOLS``,
so it can never drift from the registered surface.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

SPEND_CONFIRM_ARG = "confirm_spend"

#: Tools that move money or burn purchased credits. Each one refuses unless the
#: caller passes ``confirm_spend=True``; the refusal carries ``blocked.balance``.
SPEND_TOOLS = frozenset({"pry_buy_pack", "pry_x402_pricing_charge"})

#: Tools that read a balance/pricing surface — free, but they are the guard rail
#: a caller should read *before* a spend tool, so they stay ungated and visible.
BALANCE_TOOLS = frozenset({"pry_balance", "pry_x402_pricing"})

#: Long-running search entries. ``max_ms`` bounds them and a timeout returns a
#: ``partial=true`` envelope instead of blocking the client.
SEARCH_TOOLS = frozenset(
    {"pry_mega_search", "pry_serp", "pry_search_templates", "pry_news", "pry_papers"}
)

DEFAULT_MAX_MS = 45_000

#: Task -> the one registered entry point that owns it. No fabricated names:
#: every value is a tool present in ``PRY_TOOLS`` (asserted in the tests).
CANONICAL: dict[str, tuple[str, ...]] = {
    "search": ("pry_mega_search", "pry_serp"),
    "scrape": ("pry_scrape", "pry_crawl"),
    "extract": ("pry_extract", "pry_template"),
    "structure": ("pry_parse_document", "pry_screenshot"),
    "data": ("pry_domain", "pry_news", "pry_events"),
    "help": ("pry_help",),
}

#: Alias -> canonical task. Kept only where a shipped workflow (or the fleet)
#: already calls the alias name; everything else is discoverable via pry_help.
ALIASES: dict[str, str] = {
    "pry_mega_search": "search",
    "pry_scrape": "scrape",
    "pry_extract": "extract",
    "pry_help": "help",
}

_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "crypto",
        ("token_", "cex_", "kol_", "dextools_", "prediction_market", "crypto_"),
    ),
    ("billing", ("balance", "buy_pack", "x402_pricing", "referrals")),
    ("actors", ("actor_",)),
    (
        "scrape",
        (
            "scrape",
            "crawl",
            "extract",
            "template",
            "screenshot",
            "parse_document",
            "enrich",
            "monitor",
            "compliance",
        ),
    ),
    (
        "search",
        (
            "search",
            "mega_search",
            "serp",
            "news",
            "papers",
            "trends",
            "sentiment",
            "domain",
            "firmographics",
            "places",
            "reviews",
            "events",
            "deals",
            "drop_alert",
        ),
    ),
    (
        "sports",
        (
            "odds",
            "arbitrage",
            "plus_ev",
            "props",
            "injuries",
            "live_",
            "scores",
            "historical_odds",
            "betting",
            "alerts",
            "books",
            "book_",
            "futures",
            "derivatives",
            "kelly",
            "lineups",
            "player_",
            "steam",
            "reverse_",
            "bet_money",
            "line_",
            "sharp_",
            "game_",
            "weather_impact",
        ),
    ),
    ("local", ("weather", "agri", "grocery", "restaurant", "resale")),
    (
        "gov",
        (
            "legal_",
            "procurement",
            "contracts",
            "grants",
            "recalls",
            "patents",
            "trademarks",
            "compliance",
        ),
    ),
    ("trade", ("freight", "energy_lmp", "imports")),
    ("travel", ("flights", "hotel")),
    ("appstore", ("app_",)),
    ("jobs", ("jobs_",)),
    ("realestate", ("realestate_",)),
)


def _leaf(name: str) -> str:
    return name[4:] if name.startswith("pry_") else name


def group_of(name: str) -> str:
    """Return the single group a tool belongs to (first rule wins)."""
    leaf = _leaf(name)
    for group, needles in _GROUPS:
        if any(leaf.startswith(n) for n in needles):
            return group
    return "data"


def _envelope(name: str, code: str, message: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tool": name,
        "error": {"code": code, "message": message},
        **extra,
    }
    return {
        "error": payload["error"],
        "content": [{"type": "text", "text": json.dumps(payload)}],
        "isError": True,
    }


def _partial(name: str, max_ms: int, started: float) -> dict[str, Any]:
    payload = {
        "tool": name,
        "status": "partial",
        "partial": True,
        "reason": "deadline_exceeded",
        "max_ms": max_ms,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "results": [],
        "next": "retry with a larger max_ms or a narrower query",
    }
    return {"partial": True, "content": [{"type": "text", "text": json.dumps(payload)}]}


def gate(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Block an unconfirmed spend; return None when the call may proceed."""
    if name in SPEND_TOOLS and arguments.get(SPEND_CONFIRM_ARG) is not True:
        return _envelope(
            name,
            "blocked.balance",
            f"{name} spends credits. Re-send with {SPEND_CONFIRM_ARG}=true after "
            f"reading pry_balance; nothing was charged.",
            blocked={"code": "blocked.balance", "requires": SPEND_CONFIRM_ARG},
        )
    return None


def _budget(arguments: dict[str, Any]) -> int | None:
    raw = arguments.get("max_ms")
    if raw is None:
        return None
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return None


async def surf_gate(
    name: str,
    arguments: dict[str, Any],
    inner: Callable[..., Awaitable[dict[str, Any]]],
    identity: str | None = None,
) -> dict[str, Any]:
    """Dispatch entry: spend gate first, then an optional wait_for budget."""
    blocked = gate(name, arguments)
    if blocked is not None:
        return blocked
    budget = _budget(arguments) if name in SEARCH_TOOLS else None
    if budget is None:
        return await inner(name, arguments, identity)
    started = time.monotonic()
    try:
        return await asyncio.wait_for(inner(name, arguments, identity), budget / 1000)
    except TimeoutError:
        return _partial(name, budget, started)
