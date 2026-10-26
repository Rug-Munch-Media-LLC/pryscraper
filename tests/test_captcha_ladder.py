"""Free-tier CAPTCHA ladder: policy, order, breaker, typed refusals."""

from __future__ import annotations

import pathlib

import pytest

from pry.engine.captcha import ladder as ladder_mod, probes
from pry.engine.captcha.breaker import TierBreaker
from pry.engine.captcha.ladder import solve_ladder
from pry.engine.captcha.lanes import Challenge, LaneOutcome
from pry.engine.captcha.tiers import RETIRED_PROVIDERS, ordered_tiers

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "pry" / "engine" / "captcha"
SRC = PKG.parents[1]
CLASS = "recaptcha_v2"


async def _allow(_url: str) -> tuple[bool, str]:
    return True, "allowed"


async def _robots(_url: str) -> tuple[bool, str]:
    return False, "blocked.robots"


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ladder_mod.settings, "captcha_enabled", True)
    monkeypatch.setattr(ladder_mod.settings, "captcha_max_seconds", 30.0)
    monkeypatch.setattr(ladder_mod, "solver_allowed", _allow)


def _challenge() -> Challenge:
    return Challenge(url="https://example.com/page", captcha_type=CLASS, sitekey="k")


# ── (a) the paid surface is gone ──────────────────────────────────────────


def test_retired_providers_are_declared_with_reason() -> None:
    assert dict(RETIRED_PROVIDERS) == {
        "capsolver": "paid — removed by policy",
        "2captcha": "paid — removed by policy",
    }


def test_no_paid_provider_is_named_outside_the_retired_list() -> None:
    hits = [
        f"{path.name}:{name}"
        for path in PKG.rglob("*.py")
        if path.name != "tiers.py"
        for name in ("capsolver", "2captcha")
        if name in path.read_text(encoding="utf-8").lower()
    ]
    assert hits == []


def test_no_paid_solver_endpoint_survives_anywhere_in_src() -> None:
    hits = [
        str(path)
        for path in SRC.rglob("*.py")
        if any(
            url in path.read_text(encoding="utf-8").lower()
            for url in ("api.capsolver.com", "2captcha.com/in.php", "2captcha.com/res.php")
        )
    ]
    assert hits == []


# ── (b) order and skip-on-missing-capability ─────────────────────────────


def test_tier_order_is_expected_cost_times_latency() -> None:
    assert [t.tier for t in ordered_tiers()] == ["T0", "T1", "T3", "T4", "T2", "T5"]


@pytest.mark.asyncio
async def test_absent_capability_is_skipped_not_attempted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probes, "available", lambda _cap: False)
    calls: list[str] = []

    async def _never(tier: str, _challenge: Challenge, _remaining: float) -> LaneOutcome:
        calls.append(tier)
        return LaneOutcome("solved", "x")

    monkeypatch.setattr(ladder_mod, "run_tier", _never)
    result = await solve_ladder(_challenge(), breaker=TierBreaker())
    assert calls == []
    assert result.status == "unavailable.model"
    assert [a.status for a in result.attempts] == ["skipped"] * 6
    assert result.tiers_tried == []


@pytest.mark.asyncio
async def test_missing_browser_reports_unavailable_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probes, "available", lambda cap: cap != "patchright")

    async def _unsolved(_tier: str, _challenge: Challenge, _remaining: float) -> LaneOutcome:
        return LaneOutcome("unsolved", "x")

    monkeypatch.setattr(ladder_mod, "run_tier", _unsolved)
    result = await solve_ladder(_challenge(), breaker=TierBreaker())
    last = result.attempts[-1]
    assert last.tier == "T5"
    assert last.reason.startswith("unavailable.browser")
    assert result.status == "blocked.captcha_unsolved"


@pytest.mark.asyncio
async def test_solves_at_the_first_successful_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probes, "available", lambda _cap: True)

    async def _run(tier: str, _challenge: Challenge, _remaining: float) -> LaneOutcome:
        if tier == "T1":
            return LaneOutcome("solved", "js", token="tok")
        return LaneOutcome("unsolved", "x")

    monkeypatch.setattr(ladder_mod, "run_tier", _run)
    result = await solve_ladder(_challenge(), breaker=TierBreaker())
    assert (result.status, result.provider, result.token) == ("solved", "T1", "tok")
    assert [a.tier for a in result.attempts] == ["T0", "T1"]


# ── (c) circuit breaker ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_breaker_opens_and_is_reported_in_the_trail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(probes, "available", lambda _cap: True)

    async def _unsolved(_tier: str, _challenge: Challenge, _remaining: float) -> LaneOutcome:
        return LaneOutcome("unsolved", "x")

    monkeypatch.setattr(ladder_mod, "run_tier", _unsolved)
    clock = [0.0]
    breaker = TierBreaker(limit=3, window_s=60.0, clock=lambda: clock[0])
    for _ in range(3):
        await solve_ladder(_challenge(), breaker=breaker)
    result = await solve_ladder(_challenge(), breaker=breaker)
    assert result.tiers_tried == []
    assert all(a.reason.startswith("breaker.open") for a in result.attempts)
    assert breaker.snapshot()[f"T0:{CLASS}"] == 3


# ── (d) typed refusals ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unsolvable_returns_typed_refusal_with_class_and_tiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(probes, "available", lambda _cap: True)

    async def _unsolved(_tier: str, _challenge: Challenge, _remaining: float) -> LaneOutcome:
        return LaneOutcome("unsolved", "x")

    monkeypatch.setattr(ladder_mod, "run_tier", _unsolved)
    result = await solve_ladder(_challenge(), breaker=TierBreaker())
    assert result.token is None
    assert result.status == "blocked.captcha_unsolved"
    assert result.captcha_class == CLASS
    assert result.tiers_tried == ["T0", "T1", "T3", "T4", "T2", "T5"]
    assert all(a.line().startswith(a.tier) for a in result.attempts)


@pytest.mark.asyncio
async def test_disabled_ladder_refuses_instead_of_solving(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ladder_mod.settings, "captcha_enabled", False)
    result = await solve_ladder(_challenge(), breaker=TierBreaker())
    assert (result.status, result.attempts, result.token) == ("disabled", [], None)


# ── (e) robots is terminal with zero attempts ────────────────────────────


@pytest.mark.asyncio
async def test_robots_is_terminal_with_no_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ladder_mod, "solver_allowed", _robots)
    calls: list[str] = []

    async def _never(tier: str, _challenge: Challenge, _remaining: float) -> LaneOutcome:
        calls.append(tier)
        return LaneOutcome("solved", "x")

    monkeypatch.setattr(ladder_mod, "run_tier", _never)
    result = await solve_ladder(_challenge(), breaker=TierBreaker())
    assert result.status == "blocked.robots"
    assert result.attempts == []
    assert result.tiers_tried == []
    assert calls == []
