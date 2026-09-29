"""Per-tier health that PERSISTS across container restarts.

WHY THIS EXISTS. The in-process Prometheus counters answer "how is this tier
doing right now" and are reset every time the container is rebuilt — which on
this host is often, because the image is built from source. Measured on
2026-08-29 immediately after a rebuild, /metrics could account for exactly ONE
successful scrape, so a question like "does premium_proxy ever win?" was
unanswerable from telemetry and had to be answered by reading a backtest file.

So: a small JSON file, written on every attempt, read by a status command. Not
a replacement for Prometheus — a floor under it, so a tier's value is still
knowable when the counters have been zeroed by a deploy.

WHAT IT RECORDS PER TIER
  attempts, wins, and the median attempt cost. Wins are the only number that
  matters for deciding whether a rung earns its place; cost is what you pay
  when it loses.

The measured justification for the file existing, not the argument for it:
over 8 sources the committed baseline recorded by_via {direct: 4,
flaresolverr: 1} and premium_proxy: 0. The last three rungs of the ladder
(premium_proxy, archive, google_cache) won ZERO and cost 25-45s each on every
failure. That is a fact about the ladder, and it was invisible in telemetry.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path(
    os.getenv("PRY_TIER_HEALTH_PATH", "/app/pry-data/tier_health.json")
)

_FIELDS = ("attempts", "wins", "losses", "cost_ms_total")


def _load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def record(
    tier: str,
    *,
    won: bool,
    cost_ms: float,
    path: Path | None = None,
) -> None:
    """Record one tier attempt. Never raises — health is observability."""
    target = path or DEFAULT_PATH
    try:
        data = _load(target)
        entry = data.get(tier) or {}
        entry["attempts"] = int(entry.get("attempts", 0)) + 1
        entry["wins" if won else "losses"] = int(entry.get("wins" if won else "losses", 0)) + 1
        entry["cost_ms_total"] = round(float(entry.get("cost_ms_total", 0.0)) + cost_ms, 1)
        data[tier] = entry
        data["_updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        target.parent.mkdir(parents=True, exist_ok=True)
        # Atomic replace: a half-written health file is worse than a stale one,
        # and this is written from a request path.
        with tempfile.NamedTemporaryFile(
            "w", dir=target.parent, delete=False, suffix=".tmp"
        ) as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            tmp = Path(fh.name)
        tmp.replace(target)
    except (OSError, TypeError, ValueError):
        return


def report(path: Path | None = None) -> str:
    """A ranked table: what wins, what burns time and returns nothing."""
    target = path or DEFAULT_PATH
    data = _load(target)
    tiers = {k: v for k, v in data.items() if not k.startswith("_") and isinstance(v, dict)}
    if not tiers:
        return "no tier health recorded yet"
    lines = [
        f"{'tier':<20} {'att':>4} {'win':>4} {'lose':>5} {'win%':>6} {'med_ms':>8} {'wasted_s':>10}",
    ]
    rows = []
    for tier, e in tiers.items():
        att = int(e.get("attempts", 0))
        win = int(e.get("wins", 0))
        lose = int(e.get("losses", 0))
        cost = float(e.get("cost_ms_total", 0.0))
        pct = (win / att * 100) if att else 0.0
        wasted = cost - (cost * (win / att if att else 0))
        rows.append((tier, att, win, lose, pct, cost / att if att else 0, wasted / 1000))
    for tier, att, win, lose, pct, med, wasted in sorted(rows, key=lambda r: -r[4]):
        lines.append(
            f"{tier:<20} {att:>4} {win:>4} {lose:>5} {pct:>5.0f}% {med:>8.0f} {wasted:>10.1f}"
        )
    lines.append("")
    lines.append("wasted_s = time spent on attempts that did not win the scrape.")
    dead = [r[0] for r in rows if r[2] == 0 and r[1] >= 3]
    if dead:
        lines.append(f"NEVER WON (>=3 attempts): {', '.join(dead)}")
    return "\n".join(lines)


__all__ = ["DEFAULT_PATH", "record", "report"]
