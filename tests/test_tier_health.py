"""Tests for the persistent per-tier health store and its skip filter.

``pry.engine.tier_health`` shipped with no tests. ``should_skip`` decides
whether a rung of the fallback ladder is dropped before the scrape starts, so
BOTH directions are pinned: a rung with enough evidence of never winning is
dropped, and a working rung is NEVER dropped. The second is the safety
property — one win is enough to keep a tier, because the intent is not to
abandon a working rung on a bad day.

Every test writes its health file under ``tmp_path``. The production path is
``/app/pry-data/tier_health.json`` and is never touched from a test.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pry.engine import tier_health
from pry.engine.tier_health import should_skip

_SKIP_ENV = "PRY_TIER_SKIP_ZERO_WIN"
_MIN_ENV = "PRY_TIER_MIN_EVIDENCE"


def _blind(path: Path, tier: str, *, attempts: int, cost_ms_each: float = 30_000) -> None:
    """A tier that burned ``attempts`` attempts and won none of them."""
    for _ in range(attempts):
        tier_health.record(tier, won=False, cost_ms=cost_ms_each, path=path)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both switches are env-driven; a stray value would silently pass tests."""
    monkeypatch.delenv(_SKIP_ENV, raising=False)
    monkeypatch.setenv(_MIN_ENV, str(tier_health.MIN_EVIDENCE_ATTEMPTS))


def test_enough_attempts_and_no_wins_is_skipped_with_a_costed_reason(tmp_path: Path) -> None:
    """The reason must carry the evidence AND the cost, or it says nothing."""
    path = tmp_path / "h.json"
    path.write_text(
        json.dumps(
            {
                "_policy": tier_health.POLICY_VERSION,
                "camoufox": {"attempts": 4, "wins": 0, "cost_ms_total": 120_000},
            }
        )
    )
    skip, reason = should_skip("camoufox", path=path)
    assert skip is True
    assert "4_attempts" in reason, reason
    assert "120s" in reason, reason


def test_one_win_keeps_a_tier_however_many_losses_follow(tmp_path: Path) -> None:
    """The safety property: a rung that has ever won is never abandoned."""
    path = tmp_path / "h.json"
    tier_health.record("tor", won=True, cost_ms=1_200, path=path)
    for _ in range(40):
        tier_health.record("tor", won=False, cost_ms=45_000, path=path)
    skip, reason = should_skip("tor", path=path)
    assert skip is False
    assert reason == "has_wins(1)"


def test_one_loss_is_not_evidence(tmp_path: Path) -> None:
    path = tmp_path / "h.json"
    tier_health.record("playwright", won=False, cost_ms=45_000, path=path)
    skip, reason = should_skip("playwright", path=path)
    assert skip is False
    assert reason == f"insufficient_evidence(1<{tier_health.MIN_EVIDENCE_ATTEMPTS})"


def test_below_the_threshold_a_tier_is_kept_however_bad_it_looks(tmp_path: Path) -> None:
    path = tmp_path / "h.json"
    _blind(path, "google_cache", attempts=tier_health.MIN_EVIDENCE_ATTEMPTS - 1, cost_ms_each=3_000)
    skip, reason = should_skip("google_cache", path=path)
    assert skip is False
    assert reason.startswith("insufficient_evidence(")


def test_no_evidence_is_reported_differently_from_insufficient(tmp_path: Path) -> None:
    """A caller must be able to tell "never measured" from "barely measured"."""
    path = tmp_path / "h.json"
    path.write_text(json.dumps({"direct": {"attempts": 1, "wins": 1, "cost_ms_total": 10}}))
    unknown = should_skip("camoufox", path=path)
    thin = should_skip("direct", path=path)
    expected = (False, "no_evidence")
    assert unknown == expected
    assert thin[0] is False
    assert thin[1] != unknown[1]


def test_a_missing_file_is_no_evidence_not_a_crash(tmp_path: Path) -> None:
    expected = (False, "no_evidence")
    assert should_skip("direct", path=tmp_path / "nope" / "absent.json") == expected


def test_a_corrupt_file_is_no_evidence(tmp_path: Path) -> None:
    path = tmp_path / "h.json"
    path.write_text("{not json")
    expected = (False, "no_evidence")
    assert should_skip("direct", path=path) == expected


def test_skip_is_disabled_by_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "h.json"
    _blind(path, "premium_proxy", attempts=9, cost_ms_each=2_000)
    assert should_skip("premium_proxy", path=path)[0] is True
    monkeypatch.setenv(_SKIP_ENV, "0")
    expected = (False, "skip_disabled")
    assert should_skip("premium_proxy", path=path) == expected


def test_the_threshold_is_a_setting_not_a_literal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the threshold is hardcoded in the guard, a deployment cannot move it."""
    path = tmp_path / "h.json"
    _blind(path, "graphql", attempts=5, cost_ms_each=1_000)
    assert should_skip("graphql", path=path)[0] is True
    monkeypatch.setattr(tier_health, "MIN_EVIDENCE_ATTEMPTS", 9, raising=True)
    expected = (False, "insufficient_evidence(5<9)")
    assert should_skip("graphql", path=path) == expected


def test_the_threshold_constant_is_read_from_its_env_var() -> None:
    src = Path(tier_health.__file__).read_text()
    assert f'os.getenv("{_MIN_ENV}"' in src
    assert "MIN_EVIDENCE_ATTEMPTS = 3" not in src


def test_a_failed_write_leaves_the_health_file_usable(tmp_path: Path) -> None:
    """Health is observability: a write failure must not break a scrape.

    The path sits under a *file*, so the mkdir/rename inside ``record``
    raises OSError. The record call has to swallow it.
    """
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    tier_health.record("direct", won=True, cost_ms=5, path=blocker / "nested" / "h.json")
    expected = (False, "no_evidence")
    assert should_skip("direct", path=blocker / "nested" / "h.json") == expected


def test_record_writes_a_file_the_filter_can_read(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "h.json"
    _blind(path, "mobile_app", attempts=tier_health.MIN_EVIDENCE_ATTEMPTS, cost_ms_each=2_500)
    assert path.exists()
    skip, reason = should_skip("mobile_app", path=path)
    assert skip is True
    assert f"{tier_health.MIN_EVIDENCE_ATTEMPTS * 2.5:.0f}s" in reason  # 3 x 2.5s, 0dp


def test_report_names_the_never_won_tiers(tmp_path: Path) -> None:
    path = tmp_path / "h.json"
    _blind(path, "archive", attempts=4, cost_ms_each=30_000)
    tier_health.record("direct", won=True, cost_ms=1_000, path=path)
    out = tier_health.report(path)
    assert "NEVER WON (>=3 attempts): archive" in out
    assert any(line.startswith("direct") for line in out.splitlines())


def test_health_counters_survive_a_reload(tmp_path: Path) -> None:
    """The point of the file: the counters outlive the process that made them."""
    path = tmp_path / "h.json"
    _blind(path, "ai_visual", attempts=3, cost_ms_each=2_000)
    raw: dict[str, Any] = json.loads(path.read_text())
    assert raw["ai_visual"]["attempts"] == 3
    assert raw["ai_visual"]["losses"] == 3
    assert should_skip("ai_visual", path=path)[0] is True
