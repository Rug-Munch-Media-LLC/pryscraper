"""Pry — bounded per-URL failure state: attempt cap, backoff, terminal state.

The tier ladder is already bounded *per call* (per-tier retry configs and the
ladder budget). The unbounded consumer sits one level up: a caller retrying the
same URL forever. Measured 2026-10-23 — one ``medium.com`` URL reached
FlareSolverr 35 times in 55 minutes (~3/min at the peak), each solve burning a
browser slot to fail again, while ``cloudscraper`` logged ~86 tier failures per
2 h over the same handful of dead targets.

A URL is the only key every caller shares (HTTP route, monitor scheduler, MCP
bridge, cron script), so the state lives here, keyed by URL. After
``PRY_URL_MAX_ATTEMPTS`` consecutive failures (default 3) the URL is TERMINAL
for a cooldown that doubles per additional failure — base 60 s, capped at
900 s. While terminal the caller answers from this module and never touches a
tier, so a permanently dead target stops consuming the solver. One success
clears the state.

Bounded memory: the table is capped at ``_MAX_ENTRIES`` and pruned on write.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

_MAX_ENTRIES = 2048
_MAX_BACKOFF_S = 900.0
_BASE_BACKOFF_S = 60.0
_DEFAULT_MAX_ATTEMPTS = 3


@dataclass
class _State:
    """Consecutive failures for one URL plus when the last one happened."""

    attempts: int = 0
    failed_at: float = 0.0


_LOCK = threading.Lock()
_STATES: dict[str, _State] = {}


def _env_float(name: str, default: float, floor: float) -> float:
    try:
        return max(floor, float(os.getenv(name, str(default))))
    except ValueError:
        return default


def max_attempts() -> int:
    """Consecutive failures allowed before the URL becomes terminal."""
    return int(_env_float("PRY_URL_MAX_ATTEMPTS", _DEFAULT_MAX_ATTEMPTS, 1))


def cooldown_s(attempts: int) -> float:
    """Exponential cooldown after the cap: 1x, 2x, 4x ... capped at 15 min."""
    over = max(0, attempts - max_attempts())
    base = _env_float("PRY_URL_BACKOFF_BASE_S", _BASE_BACKOFF_S, 1.0)
    cap = _env_float("PRY_URL_BACKOFF_MAX_S", _MAX_BACKOFF_S, base)
    return min(base * (2**over), cap)


def terminal_reason(url: str, now: float | None = None) -> str | None:
    """Return why ``url`` is terminal, or None when it may be tried again."""
    with _LOCK:
        state = _STATES.get(url)
        if state is None or state.attempts < max_attempts():
            return None
        remaining = state.failed_at + cooldown_s(state.attempts) - (now or time.monotonic())
        if remaining <= 0:
            return None
        return (
            f"url_terminal_after_{state.attempts}_attempts:"
            f"retry_after_{int(remaining) + 1}s"
        )


def record_failure(url: str) -> int:
    """Count one failed scrape of ``url``; returns consecutive failures."""
    with _LOCK:
        if len(_STATES) >= _MAX_ENTRIES:
            _prune_locked()
        state = _STATES.setdefault(url, _State())
        state.attempts += 1
        state.failed_at = time.monotonic()
        return state.attempts


def record_success(url: str) -> None:
    """Clear the failure history for ``url`` (a reachable target is not dead)."""
    with _LOCK:
        _STATES.pop(url, None)


def reset() -> None:
    """Drop all state (tests and long-running workers that rotate targets)."""
    with _LOCK:
        _STATES.clear()


def _prune_locked() -> None:
    """Evict the oldest half of the table; caller holds ``_LOCK``."""
    oldest = sorted(_STATES.items(), key=lambda kv: kv[1].failed_at)
    for url, _state in oldest[: max(1, len(oldest) // 2)]:
        _STATES.pop(url, None)


def snapshot() -> dict[str, int]:
    """Read-only view of ``{url: consecutive_failures}`` for diagnostics."""
    with _LOCK:
        return {url: state.attempts for url, state in _STATES.items()}


__all__ = [
    "cooldown_s",
    "max_attempts",
    "record_failure",
    "record_success",
    "reset",
    "snapshot",
    "terminal_reason",
]
