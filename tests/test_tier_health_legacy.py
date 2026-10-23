"""Pre-upgrade evidence must not throttle a ladder it was not gathered against.

The live store on 2026-10-23 held ``playwright`` at 0 wins / 0.4 ms (a missing
browser recorded as 41 losses) and ``premium_proxy`` — the only PAID rung — at
0 wins in 71 attempts. Both histories were written by the old policy, which
disabled a tier for 14 days on 3 losses, so neither may condemn the FIXED
ladder (playwright bound in f42d3975, premium proxy unpinned in the same
commit). ``probation`` retires that evidence once per store; this pins it.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pry.engine import tier_health as th
from pry.engine.tier_health import health_alerts, record, should_skip

if TYPE_CHECKING:
    from pathlib import Path

_NOW = 1_792_700_000.0
_LEGACY = {
    "premium_proxy": {
        "attempts": 41,
        "wins": 0,
        "losses": 41,
        "cost_ms_total": 26_024.0,
        "last_seen": _NOW - 60.0,
    },
    "playwright": {
        "attempts": 41,
        "wins": 0,
        "losses": 41,
        "cost_ms_total": 17.0,
        "last_seen": _NOW - 60.0,
    },
}


def _legacy(path: Path) -> Path:
    """A store written before the retry policy existed: no ``_policy`` marker."""
    path.write_text(json.dumps(_LEGACY))
    return path


def test_legacy_evidence_is_probation_not_a_verdict(tmp_path: Path) -> None:
    path = _legacy(tmp_path / "h.json")
    assert should_skip("premium_proxy", path=path, now=_NOW) == (
        False,
        "legacy_evidence_probation",
    )
    assert should_skip("playwright", path=path, now=_NOW) == (
        False,
        "legacy_evidence_probation",
    )


def test_a_record_retires_old_evidence_once_and_keeps_the_history(tmp_path: Path) -> None:
    path = _legacy(tmp_path / "h.json")
    record("direct", won=True, cost_ms=120.0, path=path)
    data = json.loads(path.read_text())
    assert data["_policy"] == th.POLICY_VERSION
    # Counters are kept: report() still shows the wasted time.
    assert data["premium_proxy"]["attempts"] == 41
    assert data["premium_proxy"]["probation_until"] > _NOW


def test_probation_expires_and_ordinary_backoff_resumes(tmp_path: Path) -> None:
    path = _legacy(tmp_path / "h.json")
    record("direct", won=True, cost_ms=120.0, path=path)
    data = json.loads(path.read_text())
    until = data["premium_proxy"]["probation_until"]
    assert should_skip("premium_proxy", path=path, now=until - 1)[0] is False
    skip, reason = should_skip("premium_proxy", path=path, now=until + 1)
    assert skip is True
    assert reason.startswith("zero_wins_in_41_attempts")


def test_playwright_stays_unskipped_after_probation(tmp_path: Path) -> None:
    """Its 0.4 ms samples never executed, so they are not tier evidence at all."""
    path = _legacy(tmp_path / "h.json")
    record("direct", won=True, cost_ms=120.0, path=path)
    until = json.loads(path.read_text())["playwright"]["probation_until"]
    skip, reason = should_skip("playwright", path=path, now=until + 1)
    assert skip is False
    assert reason.startswith("not_executed(")
    assert any(a["kind"] == "instant_fail" for a in health_alerts(path))
