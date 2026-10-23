"""FlareSolverr deadlines must sit strictly inside the ladder's tier deadline."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import pytest

from pry.engine.flare_budget import (
    DEFAULT_TIER_S,
    client_budget_s,
    solve_budget_s,
    tier_deadline_s,
)


def test_default_deadline_is_the_ladder_budget() -> None:
    assert tier_deadline_s() == DEFAULT_TIER_S == 45.0


@pytest.mark.parametrize("env_s", ["45", "12", "90", "garbage", "", "0", "-5"])
def test_budgets_are_strictly_ordered(monkeypatch: pytest.MonkeyPatch, env_s: str) -> None:
    """solve <= client < deadline, for every deadline a deployment can set."""
    monkeypatch.setenv("PRY_TIER_TIMEOUT_S", env_s)
    deadline = tier_deadline_s()
    client_s = client_budget_s()
    solve_s = solve_budget_s()
    assert solve_s <= client_s < deadline, (solve_s, client_s, deadline)


def test_default_split(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_TIER_TIMEOUT_S", "45")
    assert client_budget_s() == 44.0
    assert solve_budget_s() == 40.0


@pytest.mark.parametrize("requested", [60.0, 90.0, 300.0])
def test_a_longer_request_is_clamped_to_the_ladder(
    monkeypatch: pytest.MonkeyPatch, requested: float
) -> None:
    """The 60 s constant class: a caller can never outlive the ladder."""
    monkeypatch.setenv("PRY_TIER_TIMEOUT_S", "45")
    client_s = client_budget_s(requested)
    assert client_s == 44.0
    assert int(solve_budget_s() * 1000) == 40_000


def test_a_shorter_request_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_TIER_TIMEOUT_S", "45")
    assert client_budget_s(30) == 30.0
    assert int(solve_budget_s() * 1000) == 40_000


def test_garbage_request_falls_back_to_the_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_TIER_TIMEOUT_S", "45")
    assert client_budget_s("nonsense") == 44.0  # type: ignore[arg-type]
