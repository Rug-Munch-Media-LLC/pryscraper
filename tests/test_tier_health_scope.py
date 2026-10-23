"""Domain-scoped tier health + honest win/loss recording.

The production incident: ``tier_health.json`` was keyed by tier name alone.
Ten tiers sat at attempts=3, wins=0 — several with ``cost_ms_total=0`` (never
executed) — and the 15-tier ladder collapsed to 4 on EVERY domain. These tests
pin the three properties that prevent a repeat:

* a zero-win record on domain A never skips tier X on domain B;
* a record with no executed sample (``cost_ms_total == 0``) is not evidence;
* a tier that could not run because its dependency was missing is not a loss.

The orchestrator-side half of the same contract (what the chain records after
block detection) lives in ``test_tier_health_orchestrate.py``.

SPDX-License-Identifier: MIT
Copyright (c) 2026 Rug Munch Media LLC
"""

from __future__ import annotations

import json
import time
from typing import Any

from pry.engine import tier_health


def _seed(path: Any, payload: dict[str, Any]) -> None:
    payload.setdefault("_policy", tier_health.POLICY_VERSION)
    path.write_text(json.dumps(payload))


def test_a_zero_win_tier_on_domain_a_does_not_skip_domain_b(tmp_path: Any) -> None:
    path = tmp_path / "h.json"
    for _ in range(tier_health.MIN_EVIDENCE_ATTEMPTS):
        tier_health.record("camoufox", won=False, cost_ms=30_000, path=path, domain="a.example")
    assert tier_health.should_skip("camoufox", path=path, domain="a.example")[0] is True
    assert tier_health.should_skip("camoufox", path=path, domain="b.example") == (
        False,
        "no_evidence",
    )
    # The write is domain-scoped; no unscoped key exists to poison other sites.
    raw = json.loads(path.read_text())
    assert "a.example|camoufox" in raw
    assert "camoufox" not in raw


def test_a_tier_with_zero_executed_samples_is_never_skipped(tmp_path: Any) -> None:
    path = tmp_path / "h.json"
    _seed(
        path,
        {"a.example|direct": {"attempts": 5, "wins": 0, "losses": 5, "cost_ms_total": 0}},
    )
    assert tier_health.should_skip("direct", path=path, domain="a.example") == (
        False,
        "no_executed_samples",
    )


def test_stale_evidence_expires(tmp_path: Any) -> None:
    path = tmp_path / "h.json"
    old = time.time() - tier_health.STALE_AFTER_S - 60
    _seed(
        path,
        {
            "a.example|direct": {
                "attempts": 9,
                "wins": 0,
                "losses": 9,
                "cost_ms_total": 9_000,
                "last_seen": old,
            }
        },
    )
    assert tier_health.should_skip("direct", path=path, domain="a.example") == (
        False,
        "stale_evidence",
    )


def test_legacy_global_keys_are_dropped_on_the_next_domain_write(tmp_path: Any) -> None:
    path = tmp_path / "h.json"
    _seed(path, {"camoufox": {"attempts": 9, "wins": 0, "losses": 9, "cost_ms_total": 1_000}})
    tier_health.record("direct", won=True, cost_ms=5, path=path, domain="a.example")
    raw = json.loads(path.read_text())
    assert "camoufox" not in raw
    assert "a.example|direct" in raw


def test_an_unavailable_tier_is_not_recorded_as_a_loss(tmp_path: Any) -> None:
    path = tmp_path / "h.json"
    tier_health.record(
        "tor", won=False, cost_ms=1_000, path=path, domain="a.example", unavailable=True
    )
    assert not path.exists()
