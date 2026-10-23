# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""FlareSolverr transport for the scrape ladder.

Extracted from ``scraper.py`` on 2026-10-23 so the grandfathered engine module
does not grow (quality gate: shrink-only above 200 lines).
"""

from __future__ import annotations

import httpx

from pry.core.settings import settings
from pry.engine.flare_budget import client_budget_s, solve_budget_s


async def fetch_via_flaresolverr(url: str, timeout_s: float | None = None) -> str:
    """Fetch ``url`` through FlareSolverr, bounded by the ladder budget.

    Same policy as the ladder tier (flare_budget): solve < client <
    PRY_TIER_TIMEOUT_S. ``timeout_s`` is a ceiling, never a multiplier.
    """
    client_s = client_budget_s(timeout_s)
    payload = {
        "cmd": "request.get",
        "url": url,
        "maxTimeout": int(solve_budget_s() * 1000),
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(client_s)) as client:
        resp = await client.post(settings.flaresolverr_url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        solution = data.get("solution", {})
        if solution.get("status") == 200:
            return solution["response"]
        raise Exception(
            f"FlareSolverr status {solution.get('status')}: {str(solution.get('status', ''))[:200]}"
        )


__all__ = ["fetch_via_flaresolverr"]
