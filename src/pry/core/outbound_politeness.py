"""Pry - outbound politeness: per-key spacing + capped, jittered backoff.

Single source of truth for how fast Pry talks TO third parties (DataBus
delivery, LLM providers, webhooks). Inbound limiting lives in
``pry.core.ratelimit``; retry policy lives in ``pry.engine.retry``.

An uncapped ``2 ** attempt`` ladder turns a throttled third party into a retry
storm and gets our egress banned. Every outbound retry MUST go through
:func:`outbound_backoff`, which honours ``Retry-After`` when known, caps the
delay (30 s), adds jitter so replicas do not retry in lockstep, and spaces
consecutive attempts per key (host or provider).

"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import asyncio
import random
import time

CAP_SECONDS = 30.0
BASE_SECONDS = 0.5

_last_attempt: dict[str, float] = {}


def _delay(
    attempt: int,
    *,
    base: float = BASE_SECONDS,
    cap: float = CAP_SECONDS,
    retry_after: float | None = None,
    jitter: float = 0.25,
) -> float:
    """Return the delay for ``attempt`` (1-based), never above ``cap``."""
    if retry_after is not None and retry_after >= 0:
        return min(float(retry_after), cap)
    raw = base * (2 ** max(0, int(attempt) - 1))
    return min(raw, cap) * (1.0 + random.random() * jitter)  # noqa: S311 - backoff jitter, not crypto


async def outbound_backoff(
    key: str,
    attempt: int = 1,
    *,
    retry_after: float | None = None,
    base: float = BASE_SECONDS,
    cap: float = CAP_SECONDS,
    min_interval: float = 0.0,
) -> float:
    """Sleep the polite delay for ``key`` and return the seconds slept."""
    if len(_last_attempt) > 1024:
        _last_attempt.clear()
    wait = _delay(attempt, base=base, cap=cap, retry_after=retry_after)
    gap = min_interval - (time.monotonic() - _last_attempt.get(key, 0.0))
    if gap > 0:
        wait = min(cap, max(wait, gap))
    _last_attempt[key] = time.monotonic() + wait
    await asyncio.sleep(wait)
    return wait
