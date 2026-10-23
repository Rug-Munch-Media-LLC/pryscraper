"""FlareSolverr deadline policy — the ONE source for every FlareSolverr timeout.

The scrape ladder kills each tier at ``PRY_TIER_TIMEOUT_S`` (default 45 s, see
:meth:`pry.engine.tier_chain.TierChain._ladder_budget`). A FlareSolverr client
that asks the sidecar for more than that is not slow, it is unreachable: the
``asyncio`` kill fires first, the sidecar's own verdict (blocked / unsolved /
status 500) is discarded, and the loss is booked as a generic timeout. Measured
2026-10-22: 75 of 214 FlareSolverr losses were exactly 45.0 s, i.e. killed, not
answered; those 214 attempts averaged 20.8 s, so the ladder budget is right and
the client constants (60 s hardcoded, 90 s default) were the bug.

Three numbers, all derived and strictly ordered::

    solve (maxTimeout) <= client (httpx) < ladder deadline

- the sidecar gets ``deadline - 5 s``: it must give up and return its own
  verdict while there is still time to deliver it;
- the client gets ``deadline - 1 s`` so it never races the ladder's kill at
  exactly the deadline;
- the remaining gap is the window in which the escaped-page envelope is
  transferred (a solved page is JSON-escaped and can dwarf the page itself).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import os

DEFAULT_TIER_S = 45.0
#: Ladder deadline minus this is the sidecar's own solve budget.
SIDECAR_MARGIN_S = 5.0
#: Ladder deadline minus this is the client's HTTP budget (never equal to it).
CLIENT_MARGIN_S = 1.0
#: A browser solve under 10 s never succeeds; keep the sidecar budget sane.
MIN_SOLVE_S = 10.0


def tier_deadline_s() -> float:
    """The ladder's per-tier deadline — the number everything else must beat."""
    raw = (os.getenv("PRY_TIER_TIMEOUT_S") or "").strip()
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TIER_S
    return value if value > 0 else DEFAULT_TIER_S


def client_budget_s(requested: float | None = None) -> float:
    """Client HTTP budget: below the ladder deadline, however long is asked for.

    ``requested`` is only a ceiling. A caller asking for 60 s or 90 s gets the
    ladder-safe budget, because the ladder would kill the call anyway — the
    clamp is what stops the ``timeout_s * 1000`` pattern from ever emitting a
    ``maxTimeout`` larger than the deadline it runs inside.
    """
    floor = MIN_SOLVE_S + CLIENT_MARGIN_S
    ceiling = max(floor, tier_deadline_s() - CLIENT_MARGIN_S)
    if requested is None:
        return ceiling
    try:
        wanted = float(requested)
    except (TypeError, ValueError):
        return ceiling
    return max(floor, min(wanted, ceiling))


def solve_budget_s() -> float:
    """Sidecar ``maxTimeout``: the deadline minus the answer/transfer margin."""
    return max(MIN_SOLVE_S, tier_deadline_s() - SIDECAR_MARGIN_S)
