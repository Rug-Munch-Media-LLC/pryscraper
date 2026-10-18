"""Per-tier health that PERSISTS across container restarts.

WHY THIS EXISTS. The in-process Prometheus counters answer "how is this tier
doing right now" and are reset every time the container is rebuilt — which on
this host is often, because the image is built from source. Measured on
2026-08-29 immediately after a rebuild, /metrics could account for exactly ONE
successful scrape, so a question like "does premium_proxy ever win?" was
unanswerable from telemetry and had to be answered by reading a backtest file.

SCOPE IS (DOMAIN, TIER), NOT TIER. Until 2026-10-18 the store was keyed by tier
name alone, so a tier that lost three times on one hard target was skipped on
every other site for the life of the file. Production
``/app/pry-data/tier_health.json`` carried 10 tiers at attempts=3, wins=0 — some
with ``cost_ms_total=0``, i.e. never actually executed — collapsing the 15-tier
ladder to 4. A tier's failure on domain A says nothing about domain B, and a
sample where the tier never ran is not evidence at all.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path(os.getenv("PRY_TIER_HEALTH_PATH", "/app/pry-data/tier_health.json"))

#: Separator between domain and tier in a storage key. A domain never contains
#: it, so a key is scoped iff it does.
SEP = "|"

#: A tier must have at least this many recorded attempts before its win rate is
#: treated as evidence. Below it the sample says nothing: one loss on a tier
#: that wins half the time is not a reason to skip it.
MIN_EVIDENCE_ATTEMPTS = int(os.getenv("PRY_TIER_MIN_EVIDENCE", "3"))

#: Evidence older than this expires. A tier's value is a fact about a period,
#: not forever: a site changes its WAF, a proxy pool rotates.
STALE_AFTER_S = float(os.getenv("PRY_TIER_HEALTH_TTL_DAYS", "14")) * 86_400.0


def _key(tier: str, domain: str | None) -> str:
    return f"{domain}{SEP}{tier}" if domain else tier


def _load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        logger.warning("silent_exception_swallowed", exc_info=True)
        return {}


def _prune(data: dict[str, Any], now: float, *, scoped: bool) -> None:
    """Drop expired entries and, on a domain write, legacy unscoped keys.

    A legacy key has no domain, so it cannot be applied to one; applying it to
    all is exactly the 2026-10 poisoning. Dropping it lets a deployment heal
    without a manual ``rm``.
    """
    for key in list(data):
        if key.startswith("_"):
            continue
        entry = data[key]
        if not isinstance(entry, dict):
            del data[key]
            continue
        seen = entry.get("last_seen")
        if isinstance(seen, (int, float)) and now - float(seen) > STALE_AFTER_S:
            del data[key]
            continue
        if scoped and SEP not in key and entry.get("scope") != "global":
            del data[key]


def record(
    tier: str,
    *,
    won: bool,
    cost_ms: float,
    path: Path | None = None,
    domain: str | None = None,
    unavailable: bool = False,
) -> None:
    """Record one tier attempt. Never raises — health is observability.

    ``unavailable`` marks an attempt that never reached the network because a
    dependency was missing. That is not a loss, and charging it to the tier is
    how a dependency gap becomes "this method does not work here".
    """
    if unavailable:
        return
    target = path or DEFAULT_PATH
    try:
        now = time.time()
        data = _load(target)
        _prune(data, now, scoped=domain is not None)
        key = _key(tier, domain)
        entry = data.get(key) or {}
        entry["attempts"] = int(entry.get("attempts", 0)) + 1
        entry["wins"] = int(entry.get("wins", 0)) + int(bool(won))
        entry["losses"] = int(entry.get("losses", 0)) + int(not won)
        entry["cost_ms_total"] = round(float(entry.get("cost_ms_total", 0.0)) + cost_ms, 1)
        entry["last_seen"] = now
        entry["scope"] = "domain" if domain else "global"
        if domain:
            entry["domain"] = domain
        data[key] = entry
        data["_updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        target.parent.mkdir(parents=True, exist_ok=True)
        # Atomic replace: a half-written health file is worse than a stale one,
        # and this is written from a request path.
        with tempfile.NamedTemporaryFile("w", dir=target.parent, delete=False, suffix=".tmp") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            tmp = Path(fh.name)
        tmp.replace(target)
    except (OSError, TypeError, ValueError):
        logger.warning("silent_exception_swallowed", exc_info=True)
        return


def report(path: Path | None = None) -> str:
    """A ranked table: what wins, what burns time and returns nothing."""
    target = path or DEFAULT_PATH
    data = _load(target)
    tiers = {k: v for k, v in data.items() if not k.startswith("_") and isinstance(v, dict)}
    if not tiers:
        return "no tier health recorded yet"
    lines = [
        f"{'scope/tier':<32} {'att':>4} {'win':>4} {'lose':>5} {'win%':>6} {'med_ms':>8} {'wasted_s':>10}",
    ]
    rows = []
    for name, e in tiers.items():
        att = int(e.get("attempts", 0))
        win = int(e.get("wins", 0))
        lose = int(e.get("losses", 0))
        cost = float(e.get("cost_ms_total", 0.0))
        pct = (win / att * 100) if att else 0.0
        wasted = cost - (cost * (win / att if att else 0))
        rows.append((name, att, win, lose, pct, cost / att if att else 0, wasted / 1000))
    for name, att, win, lose, pct, med, wasted in sorted(rows, key=lambda r: -r[4]):
        lines.append(
            f"{name:<32} {att:>4} {win:>4} {lose:>5} {pct:>5.0f}% {med:>8.0f} {wasted:>10.1f}"
        )
    lines.append("")
    lines.append("wasted_s = time spent on attempts that did not win the scrape.")
    dead = [r[0] for r in rows if r[2] == 0 and r[1] >= 3 and r[5] > 0]
    if dead:
        lines.append(f"NEVER WON (>=3 attempts): {', '.join(dead)}")
    return "\n".join(lines)


__all__ = ["DEFAULT_PATH", "MIN_EVIDENCE_ATTEMPTS", "SEP", "record", "report", "should_skip"]


def should_skip(
    tier: str, *, path: Path | None = None, domain: str | None = None
) -> tuple[bool, str]:
    """True when a tier has enough domain-scoped evidence to be worth skipping.

    Returns ``(skip, reason)``. Skipping is opt-in per deployment via
    PRY_TIER_SKIP_ZERO_WIN, default ON, because the cost is asymmetric and
    measured: over 8 sources the committed baseline recorded
    by_via {direct: 4, flaresolverr: 1} — archive, google_cache and
    premium_proxy won ZERO while archive and google_cache appeared in 2 of 3
    failures at 25-45s each.

    NOT skipped: any tier that has ever won, any tier whose recorded samples
    never executed (``cost_ms_total == 0`` — nothing was learned), any tier
    whose evidence is stale, and any tier that has no evidence for THIS domain.
    ``domain=None`` reads the legacy unscoped key so existing callers and the
    report tool keep working; the scrape path always passes a domain.
    """
    if os.getenv("PRY_TIER_SKIP_ZERO_WIN", "1") != "1":
        return False, "skip_disabled"
    entry = _load(path or DEFAULT_PATH).get(_key(tier, domain))
    if not isinstance(entry, dict):
        return False, "no_evidence"
    seen = entry.get("last_seen")
    if isinstance(seen, (int, float)) and time.time() - float(seen) > STALE_AFTER_S:
        return False, "stale_evidence"
    attempts = int(entry.get("attempts", 0))
    wins = int(entry.get("wins", 0))
    cost = float(entry.get("cost_ms_total", 0.0))
    if attempts < MIN_EVIDENCE_ATTEMPTS:
        return False, f"insufficient_evidence({attempts}<{MIN_EVIDENCE_ATTEMPTS})"
    if wins > 0:
        return False, f"has_wins({wins})"
    if cost <= 0:
        # attempts>0 but zero recorded cost: the tier never executed (a missing
        # dependency, an open breaker). Zero execution is zero evidence.
        return False, "no_executed_samples"
    wasted = cost / 1000.0
    return True, f"zero_wins_in_{attempts}_attempts_wasted_{wasted:.0f}s"
