"""Pry — circuit breaker scoped per ``(tier, domain)``.

A rung that fails ``limit`` times inside ``window_s`` on one domain is skipped
for that domain only; the same rung keeps working everywhere else. That is the
difference between "this site blocks T1" and "T1 is broken" — the old
per-``(tier, class)`` key could not tell them apart and parked a working rung
for every site after one bad domain.

A tier that has an open circuit on ``domains`` distinct domains is genuinely
broken, so the breaker falls back to a tier-global open. ``domain=None`` means
"unscoped": that call lands in the tier-global bucket, which is what a caller
without a URL gets and what the single-argument call shape always did.

The breaker is constructed per fetch (or process-wide, now that domains scope
it), so it can never park a rung for a later, different page by accident.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import time
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from collections.abc import Callable

#: Distinct domains that must be blocked before a tier is globally parked.
DEFAULT_GLOBAL_DOMAINS = 3

Scope = tuple[str, str | None]


def _host(domain: str | None) -> str | None:
    """Normalise a URL or bare host to its lower-case host (None = unscoped)."""
    if domain is None:
        return None
    value = domain.strip()
    if not value:
        return None
    parsed = urlsplit(value if "://" in value else f"//{value}")
    host = parsed.hostname or value
    return host.lower().strip(".") or None


def _render(scope: Scope) -> str:
    """Diagnostic key: ``tier:domain`` when scoped, plain ``tier`` otherwise."""
    tier, domain = scope
    return f"{tier}:{domain}" if domain else tier


class TierBreaker:
    """Consecutive-failure breaker keyed by ``(tier, domain)``."""

    def __init__(
        self,
        limit: int = 3,
        window_s: float = 180.0,
        domains: int = DEFAULT_GLOBAL_DOMAINS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = limit
        self.window_s = window_s
        self.domains = domains
        self._clock = clock
        self._events: dict[Scope, list[float]] = {}

    def _recent(self, scope: Scope) -> list[float]:
        """Failures for this scope still inside the window; prunes the rest."""
        now = self._clock()
        kept = [t for t in self._events.get(scope, []) if now - t <= self.window_s]
        if kept:
            self._events[scope] = kept
        else:
            self._events.pop(scope, None)
        return kept

    def _is_open_scope(self, scope: Scope) -> bool:
        return len(self._recent(scope)) >= self.limit

    def _open_domains(self, tier: str) -> list[str]:
        """Domains where this tier's circuit is currently open."""
        return [
            domain
            for (event_tier, domain) in list(self._events)
            if event_tier == tier
            and domain is not None
            and self._is_open_scope((event_tier, domain))
        ]

    def is_open(self, tier: str, domain: str | None = None) -> bool:
        """True when this rung must be skipped for this domain (or globally)."""
        scope = (tier, _host(domain))
        if self._is_open_scope(scope):
            return True
        return len(self._open_domains(tier)) >= self.domains

    def record(self, tier: str, ok: bool = True, *, domain: str | None = None) -> None:
        """Record one attempt; a success closes this domain's circuit only."""
        scope = (tier, _host(domain))
        if ok:
            self._events.pop(scope, None)
            return
        self._events.setdefault(scope, []).append(self._clock())

    def snapshot(self) -> dict[str, int]:
        """Open scopes -> failure count (diagnostics/telemetry)."""
        opened = [scope for scope in list(self._events) if self.is_open(*scope)]
        return {_render(scope): len(self._recent(scope)) for scope in opened}
