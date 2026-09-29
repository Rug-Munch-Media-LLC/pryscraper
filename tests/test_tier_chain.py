"""Tests for the fallback-chain builder and the placement of the skip filter.

REGRESSION: the skip-on-observed-zero-win filter used to run BEFORE archive /
google_cache / ai_visual / mobile_app / graphql were appended to the list. A
filter placed before the list is finished filters half a list, so those tiers
could never be skipped however many losses they accrued. Measured that day:
google_cache, mobile_app and graphql each had 4 attempts, 0 wins and ~3s
wasted and were still in the chain, while camoufox — which IS in the initial
list — was the only correct drop. A stub host of no-op lambdas drives the
builder: no live scraper, no containers.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import inspect
import json
import re
from typing import TYPE_CHECKING, Any

import pytest

from pry.engine import tier_chain, tier_health
from pry.engine.tier_chain import TierChainMixin

if TYPE_CHECKING:
    from pathlib import Path

_SKIP_ENV = "PRY_TIER_SKIP_ZERO_WIN"
#: Appended to the chain AFTER the initial literal list — where the bug hid.
LATE_TIERS = ("archive", "google_cache")
#: Gated on availability flags, so dark in the stub host's chain.
_FLAGGED_TIERS = ("ai_visual", "mobile_app", "graphql")
#: The builder's own source: the tier hooks are stubbed from it, so a renamed
#: tier cannot break this file, and the append/filter order is asserted on it.
_SOURCE = inspect.getsource(tier_chain.TierChainMixin._build_tier_order)
_TIER_ATTRS = tuple(sorted(set(re.findall(r"self\.(_tier_\w+)", _SOURCE))))


def _noop(*_a: Any, **_kw: Any) -> None:
    return None


class _StubChain(TierChainMixin):
    """No-op for every ``_tier_*``. The builder looks tiers up by NAME on the
    instance, so a setattr loop suffices. The shared ClassVar skip report is
    the only cross-test state."""

    def __init__(self) -> None:
        for name in _TIER_ATTRS:
            setattr(self, name, _noop)


def _entry(attempts: int = 4, wins: int = 0) -> dict[str, Any]:
    """A tier's health counters. ``wins=0`` is a never-winner; 1 is a keeper."""
    n, won = attempts, wins
    return {"attempts": n, "wins": won, "losses": n - won, "cost_ms_total": n * 30_000}


#: Two never-winners beside one has-won tier, for the selectivity tests.
MIXED = {"camoufox": _entry(), "archive": _entry(), "google_cache": _entry(1)}
_CONDEMNED = ("camoufox", "archive", "google_cache", "tor")


def _seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **tiers: dict[str, Any]) -> None:
    """Point the filter at a tmp health file. The real one is never touched."""
    path = tmp_path / "tier_health.json"
    path.write_text(json.dumps(dict(tiers)))
    monkeypatch.setattr(tier_health, "DEFAULT_PATH", path, raising=True)


def _build(
    host: _StubChain,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    proxy_url: str | None = None,
    **tiers: dict[str, Any],
) -> list[str]:
    """Seed health data under tmp_path, then build. The idempotence test drives
    one host through _build twice; the rest build a fresh host once."""
    _seed(tmp_path, monkeypatch, **tiers)
    chain = host._build_tier_order(proxy_url=proxy_url, premium_first=False)
    return [n for n, _f in chain]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_SKIP_ENV, raising=False)
    monkeypatch.delenv("PRY_PROXY_AFTER_TIERS", raising=False)


def test_the_skip_filter_runs_after_every_tier_has_been_appended(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REGRESSION: with both late tiers condemned, both must go. Before the
    fix they survived and only the initial-list tier (camoufox) was dropped."""
    condemned = dict.fromkeys((*LATE_TIERS, "camoufox"), _entry())
    names = _build(_StubChain(), tmp_path, monkeypatch, **condemned)
    for tier in condemned:
        assert tier not in names, f"{tier} was appended after the filter ran"


def test_a_late_tier_with_evidence_of_winning_is_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    names = _build(_StubChain(), tmp_path, monkeypatch, **dict.fromkeys(LATE_TIERS, _entry(1)))
    assert all(late in names for late in LATE_TIERS)


def test_a_never_won_tier_is_dropped_while_winners_survive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The filter is selective, not a blanket cull of the bad-news tiers."""
    host = _StubChain()
    names = _build(host, tmp_path, monkeypatch, **MIXED)
    assert "camoufox" not in names
    assert "archive" not in names
    assert names[0] == "direct"
    assert "google_cache" in names


def test_a_skip_is_reported_distinguishably_from_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "chose not to try" must not read as "tried and it failed"."""
    host = _StubChain()
    names = _build(host, tmp_path, monkeypatch, camoufox=_entry(), archive=_entry(1))
    assert "camoufox" not in names
    entry, *rest = host._last_skipped_tiers
    assert not rest
    assert entry.startswith("camoufox:")
    assert "skipped(zero_wins_in_" in entry
    # Chain membership and the report are the two halves a caller reads.
    assert "archive" in names
    assert not any("archive" in s for s in host._last_skipped_tiers)


def test_the_skip_report_covers_every_dropped_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = _StubChain()
    names = _build(host, tmp_path, monkeypatch, **dict.fromkeys(_CONDEMNED, _entry()))
    assert not set(_CONDEMNED) & set(names)
    # One report entry per drop, each naming its tier.
    assert len(host._last_skipped_tiers) == len(_CONDEMNED)
    assert {s.split(":")[0] for s in host._last_skipped_tiers} == set(_CONDEMNED)


def test_building_the_chain_twice_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host, blind = _StubChain(), {t: _entry() for t in (*LATE_TIERS, "camoufox")}
    first = _build(host, tmp_path, monkeypatch, **blind)
    first_report = list(host._last_skipped_tiers)
    second = _build(host, tmp_path, monkeypatch, **blind)
    assert first == second
    assert first_report == host._last_skipped_tiers
    for names in (first, second):
        assert len(names) == len(set(names)), f"duplicates in {names}"


def test_with_no_health_file_nothing_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = _StubChain()
    monkeypatch.setattr(tier_health, "DEFAULT_PATH", tmp_path / "absent.json", raising=True)
    names = _build(host, tmp_path, monkeypatch)
    assert host._last_skipped_tiers == []
    assert all(late in names for late in LATE_TIERS)


def test_disabling_the_switch_keeps_every_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The kill switch must restore the full ladder, not just the late tiers."""
    monkeypatch.setenv(_SKIP_ENV, "0")
    condemned = dict.fromkeys((*LATE_TIERS, "camoufox"), _entry())
    names = _build(_StubChain(), tmp_path, monkeypatch, **condemned)
    assert all(t in names for t in condemned)


def test_the_filter_cannot_run_before_an_append() -> None:
    """The flagged tiers are dark in the stub, so no health file can prove their
    ordering. Assert the order in the source: every append must sit above the
    filter, or the next late append hides again."""
    filter_at = _SOURCE.index("should_skip_tier(")
    for late in (*LATE_TIERS, *_FLAGGED_TIERS):
        assert _SOURCE.index(f'"{late}"') < filter_at, f"{late} is appended after the skip filter"


def test_the_premium_proxy_rung_keeps_its_early_position(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The late-append fix must not disturb the premium-proxy placement."""
    names = _build(_StubChain(), tmp_path, monkeypatch, proxy_url="http://proxy:1")
    assert names[:2] == ["direct", "premium_proxy"]
