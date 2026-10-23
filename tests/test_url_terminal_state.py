"""A dead URL must reach a terminal state instead of buying the solver forever.

Measured 2026-10-23: one medium.com article reached FlareSolverr 35 times in 55
minutes (~3/min at the peak), each solve burning 60 s of browser slot against a
sidecar that gives up at 15 s. The ladder was bounded per call; the caller was
not. These tests pin the per-URL cap, the exponential cooldown, success
clearing the state, bounded memory, and the one thing that actually stops the
burn: a terminal URL never touches a tier.

SPDX-License-Identifier: MIT
Copyright (c) 2026 Rug Munch Media LLC
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from pry.engine import tier_terminal_gate, url_terminal_state

_URL = "https://medium.com/blog/in-case-you-missed-it-june-2016-8505534e0ac9"


@pytest.fixture(autouse=True)
def _clean_state() -> Any:
    """Every test starts and ends with an empty table."""
    url_terminal_state.reset()
    yield
    url_terminal_state.reset()


# ---------------------------------------------------------------------------
# url_terminal_state — cap, cooldown, clearing, pruning
# ---------------------------------------------------------------------------


def test_below_cap_is_not_terminal() -> None:
    for _ in range(url_terminal_state.max_attempts() - 1):
        url_terminal_state.record_failure(_URL)
    assert url_terminal_state.terminal_reason(_URL) is None


def test_cap_makes_the_url_terminal() -> None:
    for _ in range(url_terminal_state.max_attempts()):
        url_terminal_state.record_failure(_URL)
    reason = url_terminal_state.terminal_reason(_URL)
    assert reason is not None
    assert reason.startswith(f"url_terminal_after_{url_terminal_state.max_attempts()}_attempts")


def test_cooldown_doubles_then_caps() -> None:
    cap, base = url_terminal_state.max_attempts(), url_terminal_state.cooldown_s
    assert base(cap) == 60.0
    assert base(cap + 1) == 120.0
    assert base(cap + 2) == 240.0
    assert base(cap + 10) == 900.0  # capped, not 60 * 2**10


def test_cooldown_expiry_allows_one_more_attempt() -> None:
    for _ in range(url_terminal_state.max_attempts()):
        url_terminal_state.record_failure(_URL)
    cap = url_terminal_state.max_attempts()
    future = time.monotonic() + url_terminal_state.cooldown_s(cap) + 1
    assert url_terminal_state.terminal_reason(_URL, now=future) is None


def test_success_clears_the_state() -> None:
    for _ in range(url_terminal_state.max_attempts()):
        url_terminal_state.record_failure(_URL)
    url_terminal_state.record_success(_URL)
    assert url_terminal_state.terminal_reason(_URL) is None
    assert _URL not in url_terminal_state.snapshot()


def test_table_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(url_terminal_state, "_MAX_ENTRIES", 4)
    for i in range(20):
        url_terminal_state.record_failure(f"https://dead.example/{i}")
    assert len(url_terminal_state.snapshot()) <= 4


# ---------------------------------------------------------------------------
# tier_terminal_gate — the orchestrator-facing seam
# ---------------------------------------------------------------------------


def test_gate_passes_while_the_url_is_alive() -> None:
    url_terminal_state.record_failure(_URL)
    assert tier_terminal_gate.pre_tier_check(_URL) is None


def test_gate_short_circuits_at_the_cap() -> None:
    for _ in range(url_terminal_state.max_attempts()):
        url_terminal_state.record_failure(_URL)
    result = tier_terminal_gate.pre_tier_check(_URL)
    assert result is not None
    assert result["status"] == "error"
    assert result["verdict"] == "url_terminal"
    assert result["url"] == _URL
    assert result["tiers_attempted"] == []
    assert "url_terminal_after_" in result["error"]


_FAILED = {"status": "error", "verdict": "exhausted", "url": _URL}


def test_post_outcome_counts_failures_and_success_clears() -> None:
    for _ in range(url_terminal_state.max_attempts()):
        tier_terminal_gate.post_tier_outcome(_URL, _FAILED)
    assert url_terminal_state.terminal_reason(_URL) is not None
    tier_terminal_gate.post_tier_outcome(_URL, {"status": "ok", "url": _URL, "method": "direct"})
    assert url_terminal_state.terminal_reason(_URL) is None


def test_a_winning_scrape_is_not_counted_as_a_failure() -> None:
    """Regression: success is ``status == "ok"``, never ``"success"``.

    Testing for the wrong token counted every win as a loss, so the third
    success of a healthy URL made that URL terminal — a self-inflicted outage.
    """
    win = {"status": "ok", "url": _URL, "method": "direct"}
    for _ in range(url_terminal_state.max_attempts() + 2):
        tier_terminal_gate.post_tier_outcome(_URL, win)
    assert url_terminal_state.terminal_reason(_URL) is None
    assert _URL not in url_terminal_state.snapshot()


def test_a_payload_that_never_ran_the_ladder_spends_no_budget() -> None:
    """An invalid-URL error is not evidence about the target."""
    for _ in range(url_terminal_state.max_attempts() + 2):
        tier_terminal_gate.post_tier_outcome(_URL, {"status": "error", "url": _URL, "error": "bad"})
    assert url_terminal_state.snapshot() == {}


def test_a_raised_attempt_counts_as_a_failure() -> None:
    for _ in range(url_terminal_state.max_attempts()):
        tier_terminal_gate.post_tier_outcome(_URL, None)
    assert url_terminal_state.terminal_reason(_URL) is not None
