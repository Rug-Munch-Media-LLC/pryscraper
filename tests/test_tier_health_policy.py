"""The retry policy for a zero-win tier: throttled with backoff, never dropped.

The bug this pins, measured on the live container 2026-10-23 (aggregated over
domains from /app/pry-data/tier_health.json)::

    playwright      41 attempts, 0 wins,    17 ms TOTAL (0.4 ms avg)
    premium_proxy   41 attempts, 0 wins, 26 024 ms  (PAID)
    direct          53 attempts, 0 wins, 37 800 ms  (713 ms avg)
    camoufox        65 attempts, 0 wins, 98 848 ms  (1 521 ms avg)

339 of 1206 attempts (28%) went to tiers the old rule had already killed for a
14-day TTL. Each test below pins one verdict: a throttle that always expires, a
sub-millisecond failure that is a configuration fault rather than a loss, and a
paid tier that is never disabled silently.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from pry.engine import tier_health as th
from pry.engine.tier_health import health_alerts, should_skip

_NOW = 1_800_000_000.0
_DAY = 86_400.0

#: The four verdicts, as measured; avg_ms selects how the policy classifies them.
MEASURED = {
    "playwright": {"attempts": 41, "wins": 0, "cost_ms_total": 17.0},
    "premium_proxy": {"attempts": 41, "wins": 0, "cost_ms_total": 26_024.0},
    "direct": {"attempts": 53, "wins": 0, "cost_ms_total": 37_800.0},
    "camoufox": {"attempts": 65, "wins": 0, "cost_ms_total": 98_848.0},
}


@pytest.fixture(autouse=True)
def _fresh_alerts() -> None:
    """The once-per-process alert guard is module state; reset it per test."""
    th._ALERTED.clear()


def _aged(attempts: int, age_s: float) -> dict[str, Any]:
    """A never-winning tier whose last attempt was ``age_s`` seconds ago."""
    return {
        "attempts": attempts,
        "wins": 0,
        "losses": attempts,
        "cost_ms_total": attempts * 900.0,
        "last_seen": _NOW - age_s,
    }


def _seed(path: Path, **tiers: dict[str, Any]) -> Path:
    path.write_text(json.dumps({"_policy": th.POLICY_VERSION, **tiers}))
    return path


def _measured(path: Path, tier: str, *, age_s: float = 0.0) -> Path:
    row = MEASURED[tier]
    return _seed(path, **{tier: {**row, "losses": row["attempts"], "last_seen": _NOW - age_s}})


def test_a_tier_dead_for_ten_days_is_probed_again_not_dropped(tmp_path: Path) -> None:
    """The 14-day TTL was the only revival path. A cooldown must revive sooner."""
    path = _measured(tmp_path / "h.json", "camoufox", age_s=10 * _DAY)
    skip, reason = should_skip("camoufox", path=path, now=_NOW)
    assert skip is False
    assert reason.startswith("probe_due(zero_wins_in_65_attempts")


@pytest.mark.parametrize(
    ("attempts", "age_s", "expected"),
    [
        (3, 250, True),  # 300 s window still open
        (3, 350, False),  # ...and closed past 300 s
        (4, 500, True),  # doubled to 600 s
        (4, 700, False),
        (5, 1_100, True),  # doubled to 1200 s
        (5, 1_300, False),
    ],
)
def test_the_cooldown_doubles_per_fruitless_attempt(
    tmp_path: Path, attempts: int, age_s: float, expected: bool
) -> None:
    """3 attempts -> 300 s, 4 -> 600 s, 5 -> 1200 s. Nothing is permanent."""
    path = _seed(tmp_path / "h.json", graphql=_aged(attempts, age_s))
    skip, reason = should_skip("graphql", path=path, now=_NOW)
    assert skip is expected
    assert reason.startswith("probe_due(" if expected is False else "zero_wins_in_")


def test_the_cooldown_is_capped_not_unbounded(tmp_path: Path) -> None:
    path = _seed(tmp_path / "h.json", graphql=_aged(60, _DAY - 60))
    assert should_skip("graphql", path=path, now=_NOW)[0] is True
    _seed(path, graphql=_aged(60, _DAY + 60))
    assert should_skip("graphql", path=path, now=_NOW)[0] is False


def test_the_cooldown_knobs_are_settings_not_literals(tmp_path: Path) -> None:
    path = _seed(tmp_path / "h.json", graphql=_aged(3, 100))
    assert should_skip("graphql", path=path, now=_NOW)[0] is True
    # Saved/restored by hand: the monkeypatch counter is a decrease-only ratchet.
    original, th.COOLDOWN_BASE_S = th.COOLDOWN_BASE_S, 60.0
    try:
        assert should_skip("graphql", path=path, now=_NOW)[0] is False
    finally:
        th.COOLDOWN_BASE_S = original
    src = Path(th.__file__).read_text()
    assert 'os.getenv("PRY_TIER_COOLDOWN_BASE_S"' in src
    assert "COOLDOWN_BASE_S = 300" not in src


def test_a_win_ends_the_penalty(tmp_path: Path) -> None:
    path = _seed(tmp_path / "h.json", tor={"attempts": 50, "wins": 1, "cost_ms_total": 50_000.0})
    assert should_skip("tor", path=path, now=_NOW) == (False, "has_wins(1)")


def test_instant_failures_are_config_evidence_not_tier_evidence(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """playwright's 0.4 ms 'loss' is a missing browser binary, not a bad method.

    A sub-millisecond attempt never reached the network, so it cannot condemn the
    tier — and it must be louder than a table row, or nobody installs the browser.
    """
    caplog.set_level(logging.ERROR, logger="pry.engine.tier_health")
    path = _measured(tmp_path / "h.json", "playwright", age_s=10 * _DAY)
    skip, reason = should_skip("playwright", path=path, now=_NOW)
    assert skip is False
    assert reason.startswith("not_executed(0.41ms<")
    alerts = [r for r in caplog.records if getattr(r, "alert", "") == "instant_fail"]
    assert alerts
    assert alerts[0].tier == "playwright"


def test_a_paid_zero_win_tier_is_throttled_but_never_silent(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Money is spent per request, so it is throttled — and every skip is loud."""
    caplog.set_level(logging.ERROR, logger="pry.engine.tier_health")
    path = _measured(tmp_path / "h.json", "premium_proxy")
    skip, reason = should_skip("premium_proxy", path=path, now=_NOW)
    assert skip is True
    assert reason.startswith("zero_wins_in_41_attempts")
    assert "next_probe_in_" in reason
    alerts = [r for r in caplog.records if getattr(r, "alert", "") == "paid_tier_zero_wins"]
    assert alerts
    assert alerts[0].tier == "premium_proxy"
    assert any(a["kind"] == "paid_tier_zero_wins" for a in health_alerts(path))


def test_the_alert_fires_once_per_process(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR, logger="pry.engine.tier_health")
    path = _measured(tmp_path / "h.json", "premium_proxy")
    for _ in range(5):
        should_skip("premium_proxy", path=path, now=_NOW)
    assert len([r for r in caplog.records if hasattr(r, "alert")]) == 1


def test_direct_and_camoufox_are_ordinary_zero_winners(tmp_path: Path) -> None:
    """Real latency, real requests: these genuinely lose on these hosts.

    No alert — the answer for them is the backoff and a shorter ladder, not a
    missing dependency and not a refund.
    """
    path = _seed(tmp_path / "h.json", **{t: MEASURED[t] for t in ("direct", "camoufox")})
    for tier in ("direct", "camoufox"):
        skip, reason = should_skip(tier, path=path, now=_NOW)
        assert skip is True, reason
        assert reason.startswith("zero_wins_in_")
    assert health_alerts(path) == []


def test_the_report_names_both_faults(tmp_path: Path) -> None:
    path = _seed(tmp_path / "h.json", **MEASURED)
    out = th.report(path)
    assert "INSTANT-FAIL" in out
    assert "playwright (0.41 ms avg" in out
    assert "PAID TIER WITH ZERO WINS" in out
    assert "NEVER WON (>=3 attempts):" in out


def test_a_missing_last_seen_is_treated_as_fresh(tmp_path: Path) -> None:
    """Pre-v1 and hand-written entries must not un-skip the whole ladder at once."""
    path = _seed(tmp_path / "h.json", graphql={"attempts": 5, "wins": 0, "cost_ms_total": 4_500.0})
    assert should_skip("graphql", path=path, now=_NOW)[0] is True
