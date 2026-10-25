"""Tests for the unlock ledger: ordering, repair, staleness, secret hygiene.

Fixtures only. The embed lane is injected as a fake embedder, so no network and
no vector is ever fabricated by the test rig.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pry.engine.unlock_ledger import UnlockLedger, normalize_domain, scrub_params
from pry.engine.unlock_policy import (
    STALE_AFTER_FAILURES,
    MethodRecord,
    order_candidates,
    replay_order,
)
from pry.engine.unlock_similar import EmbedLane, find_similar_domain, host_family

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

NOW = 1_800_000_000.0


@pytest.fixture
def ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[UnlockLedger]:
    """Flagged-on ledger in a throwaway file, with a frozen clock."""
    monkeypatch.setenv("PRY_UNLOCK_LEDGER", "1")
    store = UnlockLedger(path=str(tmp_path / "ledger.sqlite3"), now=lambda: NOW)
    yield store
    store.close()


def _record(method: str, *, ok: int = 0, streak: int = 0, last_ok: float | None = NOW, approved: bool = True) -> MethodRecord:
    return MethodRecord(
        domain="example.com",
        method=method,
        params={},
        selector="",
        last_ok_at=last_ok,
        ok_count=ok,
        fail_count=streak,
        fail_streak=streak,
        latency_ms=10.0,
        notes="",
        approved=approved,
    )


def test_choose_method_prefers_recent_success_then_cheapest(ledger: UnlockLedger) -> None:
    """A working, expensive method still beats a cheap method that never worked."""
    ledger.record_result("example.com", "http", ok=False)
    ledger.record_result("example.com", "headers", ok=True, latency_ms=12.0)
    assert ledger.choose_method("example.com") == "headers"


def test_ordering_prefers_cheaper_method_on_equal_wins() -> None:
    """Equal success counts resolve by METHOD_COST, then name."""
    records = [_record("flaresolverr", ok=2), _record("headers", ok=2)]
    assert replay_order(records, NOW) == ["headers", "flaresolverr"]


def test_failure_advances_to_next_candidate(ledger: UnlockLedger) -> None:
    """Three consecutive failures make a recipe stale; the next one wins."""
    for _ in range(STALE_AFTER_FAILURES):
        ledger.record_result("shop.example.com", "http", ok=False)
    ledger.record_result("shop.example.com", "api_endpoint", ok=True)
    assert ledger.choose_method("shop.example.com") == "api_endpoint"


def test_staleness_counter_marks_and_resets(ledger: UnlockLedger) -> None:
    """Streak reaches the threshold, then one success resets it to zero."""
    for _ in range(STALE_AFTER_FAILURES):
        ledger.record_result("rot.example.com", "http", ok=False)
    stale = {r.method: r for r in ledger.records("rot.example.com")}["http"]
    assert stale.is_stale
    assert stale.fail_streak == STALE_AFTER_FAILURES
    ledger.record_result("rot.example.com", "http", ok=True)
    healed = {r.method: r for r in ledger.records("rot.example.com")}["http"]
    assert healed.fail_streak == 0
    assert healed.ok_count == 1
    assert not healed.is_stale


def test_repair_records_a_new_winner(ledger: UnlockLedger) -> None:
    """Repair walks the ladder, records every trial, and stores the winner."""
    def attempt(method: str) -> tuple[bool, float]:
        return method == "api_endpoint", 40.0

    outcome = ledger.repair("docs.example.com", attempt)
    assert outcome.winner == "api_endpoint"
    assert outcome.tried[0] == "http"
    assert not outcome.needs_approval
    stored = {r.method: r for r in ledger.records("docs.example.com")}
    assert stored["api_endpoint"].ok_count == 1
    assert stored["http"].fail_count == 1
    assert ledger.choose_method("docs.example.com") == "api_endpoint"


def test_repair_bypass_winner_needs_approval_and_is_not_replayed(ledger: UnlockLedger) -> None:
    """A discovered bypass is stored, flagged, and withheld from replay."""
    def attempt(method: str) -> tuple[bool, float]:
        return method == "js_render", 900.0

    outcome = ledger.repair("spa.example.com", attempt)
    assert outcome.winner == "js_render"
    assert outcome.needs_approval
    assert ledger.choose_method("spa.example.com") is None
    assert ledger.approve("spa.example.com", "js_render")
    assert ledger.choose_method("spa.example.com") == "js_render"


def test_repair_persists_nothing_when_every_method_fails(ledger: UnlockLedger) -> None:
    """Total failure yields no winner and leaves only failure counters."""
    outcome = ledger.repair("dead.example.com", lambda method: (False, 5.0))
    assert outcome.winner is None
    assert all(not r.approved or r.ok_count == 0 for r in ledger.records("dead.example.com"))


def test_no_secrets_reach_disk(ledger: UnlockLedger, tmp_path: Path) -> None:
    """Credential-shaped params are redacted before the SQLite write."""
    ledger.record_result(
        "secure.example.com",
        "headers",
        ok=True,
        params={"api_key": "sk-live-SECRET", "cookie": "session=abc123", "endpoint": "/api/v1/items"},
        selector="#grid",
    )
    ledger.close()
    raw = (tmp_path / "ledger.sqlite3").read_bytes()
    assert b"sk-live-SECRET" not in raw
    assert b"session=abc123" not in raw
    stored = {r.method: r for r in UnlockLedger(path=str(tmp_path / "ledger.sqlite3"), now=lambda: NOW).records("secure.example.com")}["headers"]
    assert stored.params == {"api_key": "<redacted>", "cookie": "<redacted>", "endpoint": "/api/v1/items"}
    assert stored.selector == "#grid"


def test_scrub_and_normalize_helpers() -> None:
    """Host normalization folds scheme/port/www; scrubbing keeps keys only."""
    assert normalize_domain("HTTPS://WWW.Shop.Example.com:443/path?q=1") == "shop.example.com"
    assert scrub_params({"Authorization": "Bearer x", "wait_ms": 500}) == {"Authorization": "<redacted>", "wait_ms": 500}
    assert scrub_params(None) == {}


def test_choose_method_is_off_unless_flagged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Flag off means zero behaviour change for crawling."""
    monkeypatch.delenv("PRY_UNLOCK_LEDGER", raising=False)
    store = UnlockLedger(path=str(tmp_path / "off.sqlite3"), now=lambda: NOW)
    store.record_result("example.com", "http", ok=True)
    assert store.choose_method("example.com") is None
    store.close()


def test_order_candidates_appends_untouched_defaults() -> None:
    """Repair may trial defaults that were never recorded."""
    assert order_candidates([_record("http", ok=1)], NOW)[0] == "http"
    assert "flaresolverr" in order_candidates([_record("http", ok=1)], NOW)


def test_find_similar_domain_uses_embed_lane() -> None:
    """Same-family recall ranks by cosine when the lane answers."""
    vectors = {"a.example.com": [1.0, 0.0], "b.other.net": [0.0, 1.0], "a.example.com ": [1.0, 0.0]}
    lane = EmbedLane(embedder=lambda text: vectors[text])
    result = find_similar_domain("a.example.com", ["a.example.com", "b.other.net"], lane=lane)
    assert result.available
    assert result.matches == []


def test_find_similar_domain_degrades_honestly() -> None:
    """A dead lane reports available=False and falls back to host family."""
    def boom(text: str) -> list[float]:
        raise OSError("lane down")

    result = find_similar_domain("shop.example.com", ["cdn.example.com", "other.net"], lane=EmbedLane(embedder=boom))
    assert not result.available
    assert "embed lane unavailable" in result.reason
    assert result.matches == ["cdn.example.com"]
    assert host_family("shop.example.com") == "example.com"


def test_cosine_rejects_dimension_mismatch() -> None:
    """1024-d is a contract, not a hint."""
    from pry.engine.unlock_similar import cosine

    with pytest.raises(ValueError, match="dimension mismatch"):
        cosine([1.0, 0.0], [1.0, 0.0, 0.0])
