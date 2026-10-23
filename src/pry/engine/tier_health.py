"""Per-tier health that PERSISTS across container restarts.

WHY THIS EXISTS. The in-process Prometheus counters answer "how is this tier
doing right now" and reset on every rebuild — often here, since the image is
built from source. After a rebuild, /metrics could account for exactly ONE
successful scrape, so "does premium_proxy ever win?" was unanswerable.

SCOPE IS (DOMAIN, TIER), NOT TIER. Until 2026-10-18 the store was keyed by tier
name alone, so a tier that lost three times on one target was skipped on every
other site for the life of the file. Domain A's failure says nothing about B.

RETRY POLICY (2026-10-23). A zero-win tier is THROTTLED, never dropped for
good. The old rule killed a tier on 3 losses and revived it only when the
14-day TTL expired; measured live, 339 of 1206 attempts (28%) went to tiers
already zero-win for days, and ``playwright`` carried 41 attempts at 0.4 ms —
a missing browser recorded as 41 losses. Retries now use an exponential
cooldown (``COOLDOWN_BASE_S`` doubling, capped at ``COOLDOWN_MAX_S``), a
sub-millisecond "failure" is never executed rather than evidence, a PAID tier
at zero wins raises an alert instead of disappearing, and history recorded
under the old policy is put on probation once (``PROBATION_S``).
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

from pry.engine.tier_cost import PAID_TIERS, premium_proxy_cost_usd
from pry.engine.tier_health_store import POLICY_VERSION, SEP, key, load, record as _store_record

logger = logging.getLogger(__name__)

#: Storage-format aliases kept for callers/tests that reach for them.
_load, _key = load, key

DEFAULT_PATH = Path(os.getenv("PRY_TIER_HEALTH_PATH", "/app/pry-data/tier_health.json"))

#: A tier must have at least this many recorded attempts before its win rate is
#: treated as evidence. Below it the sample says nothing: one loss on a tier
#: that wins half the time is not a reason to skip it.
MIN_EVIDENCE_ATTEMPTS = int(os.getenv("PRY_TIER_MIN_EVIDENCE", "3"))

#: Evidence older than this expires. A tier's value is a fact about a period,
#: not forever: a site changes its WAF, a proxy pool rotates.
STALE_AFTER_S = float(os.getenv("PRY_TIER_HEALTH_TTL_DAYS", "14")) * 86_400.0

#: Cooldown before a still-losing tier is probed again. It DOUBLES per fruitless
#: attempt and is capped, so a tier costs one request per window — a 1-in-N probe
#: budget on any real traffic — and is never permanently absent from the ladder.
COOLDOWN_BASE_S = float(os.getenv("PRY_TIER_COOLDOWN_BASE_S", "300"))
COOLDOWN_MAX_S = float(os.getenv("PRY_TIER_COOLDOWN_MAX_S", str(24 * 3600)))

#: Faster than this and the attempt never touched the network: a missing browser
#: binary, an unimportable dependency. Zero execution is zero evidence.
MIN_EXEC_MS = float(os.getenv("PRY_TIER_MIN_EXEC_MS", "2.0"))

#: One-shot window after an upgrade in which pre-policy zero-win history cannot
#: throttle a tier: long enough for the fixed playwright/premium_proxy path to
#: be probed, short enough that a genuinely dead tier throttles again today.
PROBATION_S = float(os.getenv("PRY_TIER_PROBATION_S", str(6 * 3600)))

#: Alerts already emitted by this process, so the request path cannot spam.
_ALERTED: set[str] = set()


def record(
    tier: str,
    *,
    won: bool,
    cost_ms: float,
    path: Path | None = None,
    domain: str | None = None,
    unavailable: bool = False,
) -> None:
    """Record one tier attempt. Never raises — health is observability."""
    _store_record(
        tier,
        won=won,
        cost_ms=cost_ms,
        path=path or DEFAULT_PATH,
        domain=domain,
        unavailable=unavailable,
        stale_after_s=STALE_AFTER_S,
        min_exec_ms=MIN_EXEC_MS,
        probation_s=PROBATION_S,
    )


def _alert(kind: str, tier: str, detail: str) -> None:
    """One ERROR line per (kind, tier) per process — never per request."""
    name = f"{kind}:{tier}"
    if name in _ALERTED:
        return
    _ALERTED.add(name)
    logger.error("tier_health_alert", extra={"alert": kind, "tier": tier, "detail": detail})


def _cooldown_s(attempts: int) -> float:
    """Exponential backoff for a still-losing tier, capped at COOLDOWN_MAX_S."""
    excess = min(max(attempts - MIN_EVIDENCE_ATTEMPTS, 0), 20)
    return min(COOLDOWN_BASE_S * (2.0**excess), COOLDOWN_MAX_S)


def _paid_alert(tier: str, attempts: int) -> None:
    spend = premium_proxy_cost_usd() * attempts
    money = f", ${spend:.2f} spent" if spend > 0 else ""
    _alert("paid_tier_zero_wins", tier, f"{attempts} attempts, 0 wins{money}")


def should_skip(
    tier: str, *, path: Path | None = None, domain: str | None = None, now: float | None = None
) -> tuple[bool, str]:
    """True when a tier is inside its cooldown after a run of zero-win attempts.

    Returns ``(skip, reason)``. Skipping is opt-in per deployment via
    PRY_TIER_SKIP_ZERO_WIN, default ON, because the cost is asymmetric and
    measured: a zero-win rung at 25-45s per attempt buys nothing.

    NOT skipped: a tier that has ever won, one whose samples never executed
    (zero or sub-millisecond cost), stale evidence, or an entry inside its
    post-upgrade probation window.

    SKIPPING IS TEMPORARY. Past the evidence threshold the cooldown doubles per
    fruitless attempt (capped at COOLDOWN_MAX_S), so a fixed proxy or browser is
    picked up within hours without an operator ``rm``. A PAID tier at zero wins
    is still throttled — money burns fastest on a broken paid rung — but every
    skip is alerted and ``report()`` / ``health_alerts()`` name it.
    """
    if os.getenv("PRY_TIER_SKIP_ZERO_WIN", "1") != "1":
        return False, "skip_disabled"
    data = load(path or DEFAULT_PATH)
    entry = data.get(key(tier, domain))
    if not isinstance(entry, dict):
        return False, "no_evidence"
    if data.get("_policy") != POLICY_VERSION:
        return False, "legacy_evidence_probation"
    clock = time.time() if now is None else float(now)
    on_probation = entry.get("probation_until")
    if isinstance(on_probation, (int, float)) and clock < float(on_probation):
        return False, f"probation({float(on_probation) - clock:.0f}s left)"
    seen = entry.get("last_seen")
    if isinstance(seen, (int, float)) and clock - float(seen) > STALE_AFTER_S:
        return False, "stale_evidence"
    attempts = int(entry.get("attempts", 0))
    wins = int(entry.get("wins", 0))
    cost = float(entry.get("cost_ms_total", 0.0))
    if attempts < MIN_EVIDENCE_ATTEMPTS:
        return False, f"insufficient_evidence({attempts}<{MIN_EVIDENCE_ATTEMPTS})"
    if wins > 0:
        return False, f"has_wins({wins})"
    if cost <= 0:
        return False, "no_executed_samples"
    avg_ms = cost / attempts
    if avg_ms < MIN_EXEC_MS:
        _alert("instant_fail", tier, f"{attempts} attempts at {avg_ms:.2f} ms never executed")
        return False, f"not_executed({avg_ms:.2f}ms<{MIN_EXEC_MS}ms)"
    wasted = cost / 1000.0
    if tier in PAID_TIERS:
        _paid_alert(tier, attempts)
    cooldown = _cooldown_s(attempts)
    # No last_seen means a hand-written or pre-v1 entry: treat it as fresh so
    # malformed data cannot un-skip the whole ladder at once.
    age = clock - float(seen) if isinstance(seen, (int, float)) else 0.0
    reason = f"zero_wins_in_{attempts}_attempts_wasted_{wasted:.0f}s"
    if age < cooldown:
        return True, f"{reason}_next_probe_in_{cooldown - age:.0f}s"
    return False, f"probe_due({reason})"


def report(path: Path | None = None) -> str:
    """A ranked table: what wins, what burns time and returns nothing."""
    from pry.engine.tier_health_report import report as _report

    return _report(path)


def health_alerts(path: Path | None = None) -> list[dict[str, Any]]:
    """Machine-readable alerts: instant failures and paid tiers at zero wins."""
    from pry.engine.tier_health_report import health_alerts as _alerts

    return _alerts(path)


__all__ = [
    "COOLDOWN_BASE_S",
    "COOLDOWN_MAX_S",
    "DEFAULT_PATH",
    "MIN_EVIDENCE_ATTEMPTS",
    "MIN_EXEC_MS",
    "PAID_TIERS",
    "SEP",
    "health_alerts",
    "record",
    "report",
    "should_skip",
]
