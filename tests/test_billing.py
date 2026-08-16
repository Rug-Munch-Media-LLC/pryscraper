# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the subscription billing module (tiers + enforcement)."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import TYPE_CHECKING

from billing import TIERS, BillingEnforcer, Tier, get_tier

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


# ── Tier table ─────────────────────────────────────────────────────
def test_tier_table_has_expected_tiers() -> None:
    assert set(TIERS) == {"free", "pro", "team", "enterprise"}


def test_tier_pricing_and_quotas() -> None:
    free = TIERS["free"]
    assert free.price_usd_monthly is None
    assert free.request_quota_monthly is None  # no monthly cap, pay-per-call
    assert TIERS["pro"].price_usd_monthly == 49.0
    assert TIERS["pro"].request_quota_monthly == 50_000
    assert TIERS["team"].price_usd_monthly == 199.0
    assert TIERS["team"].request_quota_monthly == 500_000
    assert TIERS["enterprise"].price_usd_monthly is None  # custom quote
    assert TIERS["enterprise"].request_quota_monthly is None  # unlimited
    assert TIERS["enterprise"].rate_limit_rpm is None  # no rpm cap under SLA
    assert TIERS["enterprise"].concurrent_limit >= TIERS["team"].concurrent_limit


def test_tier_feature_flags() -> None:
    assert {"x402_pay_per_call", "basic_stealth"} <= TIERS["free"].feature_flags
    pro = TIERS["pro"].feature_flags
    assert {"priority_stealth", "residential_proxies", "standard_support"} <= pro
    assert "basic_stealth" not in pro
    team = TIERS["team"].feature_flags
    assert {"batch", "custom_templates", "priority_support"} <= team
    assert {"unlimited", "sla", "dedicated"} <= TIERS["enterprise"].feature_flags


def test_get_tier_case_insensitive_and_default() -> None:
    assert get_tier("PRO").name == "pro"
    assert get_tier("  Team ").name == "team"
    assert get_tier(None).name == "free"
    assert get_tier("nonexistent").name == "free"


# ── Tier resolution ────────────────────────────────────────────────
def test_resolve_tier_known_and_unknown_key() -> None:
    enforcer = BillingEnforcer(keys_config={"sk_pro": "pro", "sk_team": "team"})
    assert enforcer.resolve_tier("sk_pro").name == "pro"
    assert enforcer.resolve_tier("sk_team").name == "team"
    assert enforcer.resolve_tier("sk_unknown").name == "free"
    assert enforcer.resolve_tier(None).name == "free"


def test_resolve_tier_from_env_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRY_BILLING_KEYS", json.dumps({"sk_env": "pro"}))
    enforcer = BillingEnforcer()
    assert enforcer.resolve_tier("sk_env").name == "pro"
    assert enforcer.resolve_tier("sk_unknown").name == "free"


def test_resolve_tier_from_config_file(tmp_path: Path) -> None:
    cfg = tmp_path / "tiers.json"
    cfg.write_text(json.dumps({"sk_team": "team", "sk_bad": "platinum"}), encoding="utf-8")
    enforcer = BillingEnforcer(keys_config=cfg)
    assert enforcer.resolve_tier("sk_team").name == "team"
    # Unknown tier name in the config degrades to FREE instead of crashing.
    assert enforcer.resolve_tier("sk_bad").name == "free"


def test_resolve_tier_from_json_string() -> None:
    enforcer = BillingEnforcer(keys_config='{"sk_pro": "pro"}')
    assert enforcer.resolve_tier("sk_pro").name == "pro"


def test_invalid_config_degrades_to_free() -> None:
    enforcer = BillingEnforcer(keys_config="{not json")  # type: ignore[arg-type]
    assert enforcer.resolve_tier("anything").name == "free"


# ── Quota enforcement ──────────────────────────────────────────────
def test_quota_exceeded_returns_false() -> None:
    tier = Tier(
        name="trial",
        price_usd_monthly=None,
        request_quota_monthly=3,
        concurrent_limit=1,
        rate_limit_rpm=None,
    )
    enforcer = BillingEnforcer()
    assert all(enforcer.check_request("k", tier) for _ in range(3))
    assert not enforcer.check_request("k", tier)
    assert not enforcer.check_request("k", tier)  # stays blocked


def test_unlimited_quota_always_allowed() -> None:
    tier = Tier(
        name="trial",
        price_usd_monthly=None,
        request_quota_monthly=None,
        concurrent_limit=1,
        rate_limit_rpm=None,
    )
    enforcer = BillingEnforcer()
    for _ in range(100):
        assert enforcer.check_request("k", tier)
    assert enforcer.usage_stats("k")["request_quota_monthly"] is None


def test_monthly_quota_rolls_over(monkeypatch: pytest.MonkeyPatch) -> None:
    import billing.enforcer as enforcer_mod

    tier = Tier(
        name="trial",
        price_usd_monthly=None,
        request_quota_monthly=3,
        concurrent_limit=1,
        rate_limit_rpm=None,
    )
    enforcer = BillingEnforcer()
    for _ in range(3):
        assert enforcer.check_request("k", tier)
    assert not enforcer.check_request("k", tier)
    # New month → quota resets.
    monkeypatch.setattr(enforcer_mod, "_current_month", lambda: "2099-01")
    assert enforcer.check_request("k", tier)
    assert enforcer.usage_stats("k")["month"] == "2099-01"


def test_check_request_resolves_tier_when_omitted() -> None:
    enforcer = BillingEnforcer(keys_config={"sk_pro": "pro"})
    assert enforcer.check_request("sk_pro")
    assert enforcer.check_request("sk_pro")
    stats = enforcer.usage_stats("sk_pro")
    assert stats["tier"] == "pro"
    assert stats["month_requests"] == 2


# ── Rate limiting ──────────────────────────────────────────────────
def test_rate_limit_enforced_with_fake_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    import billing.enforcer as enforcer_mod

    clock = {"now": 1000.0}
    monkeypatch.setattr(enforcer_mod.time, "monotonic", lambda: clock["now"])
    tier = Tier(
        name="trial",
        price_usd_monthly=None,
        request_quota_monthly=None,
        concurrent_limit=1,
        rate_limit_rpm=2,
    )
    enforcer = BillingEnforcer()
    assert enforcer.check_request("k", tier)
    assert enforcer.check_request("k", tier)
    assert not enforcer.check_request("k", tier)  # rpm exhausted
    clock["now"] += 60.0
    assert enforcer.check_request("k", tier)  # window rolled over


# ── Usage stats ────────────────────────────────────────────────────
def test_usage_stats_shape() -> None:
    enforcer = BillingEnforcer(keys_config={"sk_pro": "pro"})
    assert enforcer.check_request("sk_pro")
    stats = enforcer.usage_stats("sk_pro")
    assert stats["tier"] == "pro"
    assert stats["price_usd_monthly"] == 49.0
    assert stats["request_quota_monthly"] == 50_000
    assert stats["month_requests"] == 1
    assert stats["quota_remaining"] == 49_999
    assert stats["quota_exceeded"] is False
    assert stats["concurrent_limit"] == 5
    assert stats["rate_limit_rpm"] == 120
    assert stats["rpm_remaining"] == 119
    assert stats["month"] == date.today().strftime("%Y-%m")


def test_usage_stats_unknown_key_defaults_free() -> None:
    enforcer = BillingEnforcer()
    stats = enforcer.usage_stats("nobody")
    assert stats["tier"] == "free"
    assert stats["request_quota_monthly"] is None
    assert stats["month_requests"] == 0
    assert stats["quota_remaining"] is None
    assert stats["quota_exceeded"] is False


# ── Thread safety ──────────────────────────────────────────────────
def test_thread_safe_counters() -> None:
    tier = Tier(
        name="trial",
        price_usd_monthly=None,
        request_quota_monthly=None,
        concurrent_limit=16,
        rate_limit_rpm=None,
    )
    enforcer = BillingEnforcer()

    def worker(_: int) -> int:
        return sum(1 for _ in range(100) if enforcer.check_request("shared", tier))

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(worker, range(8)))
    assert results == [100] * 8
    assert enforcer.usage_stats("shared")["month_requests"] == 800


# ── Boundedness + persistence ──────────────────────────────────────
def test_bounded_tracked_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    import billing.enforcer as enforcer_mod

    tier = Tier(
        name="trial",
        price_usd_monthly=None,
        request_quota_monthly=None,
        concurrent_limit=1,
        rate_limit_rpm=None,
    )
    enforcer = BillingEnforcer()
    monkeypatch.setattr(enforcer_mod, "MAX_TRACKED_KEYS", 3)
    for i in range(5):
        assert enforcer.check_request(f"key-{i}", tier)
    assert len(enforcer._counters) == 3
    # FIFO: the two oldest keys were evicted.
    assert "key-0" not in enforcer._counters
    assert "key-1" not in enforcer._counters
    assert "key-4" in enforcer._counters


def test_persistence_roundtrip(tmp_path: Path) -> None:
    tier = Tier(
        name="trial",
        price_usd_monthly=None,
        request_quota_monthly=3,
        concurrent_limit=1,
        rate_limit_rpm=None,
    )
    state_file = tmp_path / "billing_state.json"
    enforcer = BillingEnforcer(keys_config={"sk_1": "pro"}, persist_path=state_file)
    assert enforcer.check_request("sk_1", tier)
    assert enforcer.check_request("sk_1", tier)
    assert state_file.exists()

    reloaded = BillingEnforcer(keys_config={"sk_1": "pro"}, persist_path=state_file)
    assert reloaded.usage_stats("sk_1")["month_requests"] == 2
    assert reloaded.check_request("sk_1", tier)
    assert not reloaded.check_request("sk_1", tier)  # quota carried over


def test_corrupt_persistence_ignored(tmp_path: Path) -> None:
    state_file = tmp_path / "billing_state.json"
    state_file.write_text("{not json", encoding="utf-8")
    enforcer = BillingEnforcer(persist_path=state_file)
    assert enforcer.usage_stats("sk_1")["month_requests"] == 0


def test_reset_clears_counters() -> None:
    tier = Tier(
        name="trial",
        price_usd_monthly=None,
        request_quota_monthly=1,
        concurrent_limit=1,
        rate_limit_rpm=None,
    )
    enforcer = BillingEnforcer()
    assert enforcer.check_request("k", tier)
    assert not enforcer.check_request("k", tier)
    enforcer.reset()
    assert enforcer.check_request("k", tier)
