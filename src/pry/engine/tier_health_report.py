"""Rendered + machine-readable tier-health report.

Split out of :mod:`pry.engine.tier_health` so that module stays inside the
200-line cap while the RETRY POLICY grew. ``tier_health.report`` and
``tier_health.health_alerts`` remain the public names; both delegate here.

WHY THE REPORT CARRIES ALERTS. The live container showed two faults that were
invisible in a win-rate table: ``playwright`` at 0.4 ms average (a missing
browser binary recorded as 41 losses) and ``premium_proxy`` — the only PAID
rung — at 0 wins in 41 attempts. Neither is a verdict on the method, and
neither may be silently skipped, so both are named explicitly here and in
:func:`health_alerts`.

ONE HELPER PER SUMMARY BLOCK. Three independent questions (never won /
never executed / paid and unpaid) do not belong in the same loop: inlined they
put ``report`` at CCN 14, and each block is easier to test alone.

Keys in the store are ``domain|tier``; the flag lookup must use the TIER part or
a paid tier on any domain would be reported as if it were free.
"""

from __future__ import annotations

from typing import Any

from pry.engine import tier_health as _th

#: A tier needs this many zero-win attempts before it is worth reporting.
_REPORT_MIN_ATTEMPTS = 3

Row = tuple[str, str, int, int, int, float, float, float]


def _rows(data: dict[str, Any]) -> list[Row]:
    """(scope-key, tier, attempts, wins, losses, win%, avg_ms, wasted_s)."""
    rows: list[Row] = []
    for name, entry in data.items():
        if name.startswith("_") or not isinstance(entry, dict):
            continue
        tier = name.split(_th.SEP, 1)[-1]
        att = int(entry.get("attempts", 0))
        win = int(entry.get("wins", 0))
        lose = int(entry.get("losses", 0))
        cost = float(entry.get("cost_ms_total", 0.0))
        pct = (win / att * 100) if att else 0.0
        wasted = cost - (cost * (win / att if att else 0))
        rows.append((name, tier, att, win, lose, pct, cost / att if att else 0.0, wasted / 1000))
    return rows


def _flag(tier: str, att: int, win: int, avg_ms: float) -> str:
    if tier in _th.PAID_TIERS:
        return "PAID"
    if win == 0 and att >= _REPORT_MIN_ATTEMPTS and 0 < avg_ms < _th.MIN_EXEC_MS:
        return "INSTANT"
    return ""


def _never_won(rows: list[Row]) -> str | None:
    """Tiers that took attempts, spent measurable time, and never won."""
    dead = [r[0] for r in rows if r[3] == 0 and r[2] >= _REPORT_MIN_ATTEMPTS and r[7] > 0]
    return f"NEVER WON (>=3 attempts): {', '.join(dead)}" if dead else None


def _instant_fail(rows: list[Row]) -> str | None:
    """Tiers whose attempts never reached the network — a dependency gap."""
    instant = [r for r in rows if _flag(r[1], r[2], r[3], r[6]) == "INSTANT"]
    if not instant:
        return None
    detail = ", ".join(f"{r[0]} ({r[6]:.2f} ms avg, {r[2]} attempts)" for r in instant)
    return f"INSTANT-FAIL — never executed, fix the dependency: {detail}"


def _paid_zero_wins(rows: list[Row]) -> str | None:
    """Paid rungs that were attempted and won nothing — money, not evidence."""
    paid = [r for r in rows if r[1] in _th.PAID_TIERS and r[3] == 0 and r[2] > 0]
    if not paid:
        return None
    detail = ", ".join(f"{r[0]} ({r[2]} attempts, {r[7]:.0f}s burned)" for r in paid)
    return f"PAID TIER WITH ZERO WINS — money spent, nothing won: {detail}"


def report(path: Any = None) -> str:
    """A ranked table: what wins, what burns time and returns nothing."""
    rows = _rows(_th.load(path or _th.DEFAULT_PATH))
    if not rows:
        return "no tier health recorded yet"
    lines = [
        f"{'scope/tier':<32} {'att':>4} {'win':>4} {'lose':>5} {'win%':>6}"
        f" {'med_ms':>8} {'wasted_s':>10}  flag",
    ]
    for name, tier, att, win, lose, pct, avg, wasted in sorted(rows, key=lambda r: -r[5]):
        lines.append(
            f"{name:<32} {att:>4} {win:>4} {lose:>5} {pct:>5.0f}% {avg:>8.0f}"
            f" {wasted:>10.1f}  {_flag(tier, att, win, avg)}"
        )
    lines.append("")
    lines.append("wasted_s = time spent on attempts that did not win the scrape.")
    lines.extend(
        block for block in (_never_won(rows), _instant_fail(rows), _paid_zero_wins(rows)) if block
    )
    return "\n".join(lines)


def health_alerts(path: Any = None) -> list[dict[str, Any]]:
    """Machine-readable alerts a status endpoint or monitor can scrape.

    One dict per fault, ``kind`` being ``instant_fail`` (the tier never
    executed — a missing dependency, not a bad method) or
    ``paid_tier_zero_wins`` (paid egress failing every request).
    """
    alerts: list[dict[str, Any]] = []
    for name, tier, att, win, _lose, _pct, avg, wasted in _rows(_th.load(path or _th.DEFAULT_PATH)):
        if win or att < _REPORT_MIN_ATTEMPTS:
            continue
        if 0 < avg < _th.MIN_EXEC_MS:
            alerts.append(
                {
                    "kind": "instant_fail",
                    "tier": tier,
                    "scope": name,
                    "attempts": att,
                    "avg_ms": round(avg, 3),
                    "detail": "never reached the network: missing browser/dependency",
                }
            )
        elif tier in _th.PAID_TIERS:
            alerts.append(
                {
                    "kind": "paid_tier_zero_wins",
                    "tier": tier,
                    "scope": name,
                    "attempts": att,
                    "wasted_s": round(wasted, 1),
                    "detail": "paid egress failing every attempt",
                }
            )
    return alerts
