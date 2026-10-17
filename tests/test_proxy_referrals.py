# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the proxy provider referral catalog (pry.commerce.proxy_referrals).

proxy_referrals.py is a data-only module: it exposes the ``PROVIDER_REFERRALS``
dict that drives the affiliate/revenue program. These tests assert:

  - the catalog data structure is well-formed (required keys, types, tiers)
  - every entry is internally consistent (referral_url present, tier valid)
  - the derived lookup/listing/summary behavior in ProxyManager
    (get_proxy_referral, get_proxy_referral_url, list_proxy_referrals,
     get_proxy_referral_summary) returns correct, concrete values
  - edge cases: unknown tag lookup, empty catalog degradation

No network calls are made; ProxyManager is instantiated with a tmp_path
data_dir so no real proxy state is touched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from pry.commerce.proxy_referrals import PROVIDER_REFERRALS
from pry.engine.proxy_manager import ProxyManager

VALID_TIERS = {"premium", "standard", "budget"}

# Every provider entry must carry these keys.
REQUIRED_KEYS = {"name", "referral_url", "commission", "description", "tier"}


# ── catalog data structure ─────────────────────────────────────────────


def test_catalog_has_expected_providers() -> None:
    expected = {
        "brightdata",
        "oxylabs",
        "smartproxy",
        "iproyal",
        "webshare",
    }
    assert set(PROVIDER_REFERRALS.keys()) == expected


def test_every_entry_has_required_keys() -> None:
    for tag, info in PROVIDER_REFERRALS.items():
        assert set(info.keys()) >= REQUIRED_KEYS, f"{tag} missing required keys"


def test_every_entry_has_nonempty_referral_url() -> None:
    for tag, info in PROVIDER_REFERRALS.items():
        url = info["referral_url"]
        assert isinstance(url, str)
        assert url.startswith("https://"), f"{tag} referral_url must be https"
        assert len(url) > 10


def test_every_entry_has_valid_tier() -> None:
    for tag, info in PROVIDER_REFERRALS.items():
        assert info["tier"] in VALID_TIERS, f"{tag} has invalid tier {info['tier']!r}"


def test_every_entry_has_nonempty_commission() -> None:
    for _tag, info in PROVIDER_REFERRALS.items():
        assert isinstance(info["commission"], str)
        assert len(info["commission"]) > 0


def test_promo_code_optional_but_consistent() -> None:
    # Only some providers carry a promo_code; those that do must be non-empty strings.
    for _tag, info in PROVIDER_REFERRALS.items():
        if "promo_code" in info:
            assert isinstance(info["promo_code"], str)
            assert len(info["promo_code"]) > 0


def test_tier_distribution_has_all_three_tiers() -> None:
    tiers = {info["tier"] for info in PROVIDER_REFERRALS.values()}
    assert tiers == VALID_TIERS


# ── derived behavior via ProxyManager ──────────────────────────────────


@pytest.fixture
def pm(tmp_path: Path) -> ProxyManager:
    return ProxyManager(data_dir=tmp_path / "proxies")


def test_get_proxy_referral_returns_entry(pm: ProxyManager) -> None:
    info = pm.get_proxy_referral("brightdata")
    assert info["name"] == "Bright Data"
    assert info["tier"] == "premium"
    assert info["promo_code"] == "MUNCHCRAWL30"
    assert info["referral_url"].startswith("https://brightdata.com/")


def test_get_proxy_referral_unknown_tag_returns_empty(pm: ProxyManager) -> None:
    assert pm.get_proxy_referral("nonexistent") == {}


def test_get_proxy_referral_url(pm: ProxyManager) -> None:
    assert pm.get_proxy_referral_url("iproyal") == "https://iproyal.com/?r=munchcrawl"


def test_get_proxy_referral_url_unknown_tag_returns_empty_string(pm: ProxyManager) -> None:
    assert pm.get_proxy_referral_url("nonexistent") == ""


def test_list_proxy_referrals_includes_tag(pm: ProxyManager) -> None:
    items = pm.list_proxy_referrals()
    assert len(items) == len(PROVIDER_REFERRALS)
    tags = {item["tag"] for item in items}
    assert tags == set(PROVIDER_REFERRALS.keys())
    # each item carries the tag plus the full info dict
    for item in items:
        assert item["tag"] in PROVIDER_REFERRALS
        assert item["name"] == PROVIDER_REFERRALS[item["tag"]]["name"]


def test_get_proxy_referral_summary_counts(pm: ProxyManager) -> None:
    summary = pm.get_proxy_referral_summary()
    assert summary["total_providers"] == len(PROVIDER_REFERRALS)
    # tiers dict groups tags correctly
    assert "brightdata" in summary["tiers"]["premium"]
    assert "oxylabs" in summary["tiers"]["premium"]
    assert "smartproxy" in summary["tiers"]["standard"]
    assert "iproyal" in summary["tiers"]["budget"]
    assert "webshare" in summary["tiers"]["budget"]
    # by_tag mirrors the source catalog
    assert summary["by_tag"] == PROVIDER_REFERRALS


def test_summary_tier_counts_match_catalog(pm: ProxyManager) -> None:
    summary = pm.get_proxy_referral_summary()
    total_in_tiers = sum(len(v) for v in summary["tiers"].values())
    assert total_in_tiers == summary["total_providers"]


# ── edge cases / degradation ───────────────────────────────────────────


def test_empty_catalog_degrades_gracefully(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import pry.engine.proxy_providers as pp_mod

    # The referral catalog lives in proxy_providers (proxy_manager re-exports
    # only the lookup functions) — patch where the lookups read it.
    monkeypatch.setattr(pp_mod, "_PROXY_REFERRALS", {})
    pm = ProxyManager(data_dir=tmp_path / "proxies")
    assert pm.get_proxy_referral("brightdata") == {}
    assert pm.get_proxy_referral_url("brightdata") == ""
    assert pm.list_proxy_referrals() == []
    summary = pm.get_proxy_referral_summary()
    assert summary["total_providers"] == 0
    assert all(v == [] for v in summary["tiers"].values())
