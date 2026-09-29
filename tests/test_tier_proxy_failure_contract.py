"""Audit evidence for the bare-except review of the proxy/telemetry tier helpers.

Sibling of :mod:`tests.test_tier_failure_contract`, which holds the same audit
evidence for the scrape tiers themselves. The contract is unchanged: ``html`` is
None on any failure, so a ``None`` from a helper can never be promoted to a
success result. What these tests pin is that the two helpers which must NOT
swallow stay honest instead.

Both are the exceptions to the category-B rule and the reason it holds:

* ``_resolve_proxy_url`` degrades to the env proxy instead of reporting
  "no proxy configured" -- the latter would quietly send every request direct.
* ``_recommend_proxy`` returns ``None`` -- there is genuinely no recommendation.
* ``_record_telemetry`` never raises; telemetry is observability-only.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from typing import TYPE_CHECKING

import pry.engine.proxy_manager as pm_mod
import pry.engine.ultimate_scraper as us
from pry.engine.tier_chain import TierChainMixin
from pry.engine.ultimate_scraper import UltimateScraper

if TYPE_CHECKING:
    import pytest


class _Chain(TierChainMixin):
    """Concrete host for the mixin; the proxy helpers need no state."""


def test_resolve_proxy_url_falls_through_to_env_when_manager_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one helper that does not swallow: it degrades, it does not lie.

    A broken ProxyManager must not be reported as "no proxy configured" --
    that would quietly send every request direct.
    """

    class _Boom:
        def get_proxy_url(self) -> str:
            raise RuntimeError("proxy backend down")

    monkeypatch.setenv("PRY_PROXY_URL", "http://env-proxy:8080")
    monkeypatch.delenv("PROXY_URL", raising=False)
    monkeypatch.setattr(pm_mod, "ProxyManager", _Boom)
    assert _Chain()._resolve_proxy_url({}) == "http://env-proxy:8080"


def test_recommend_proxy_returns_none_when_the_manager_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``None`` here is the honest typed failure: there is no recommendation."""

    class _Boom:
        def get_recommendation(self, last_error: str) -> dict[str, str]:
            raise RuntimeError("proxy backend down")

    monkeypatch.setattr(pm_mod, "ProxyManager", _Boom)
    assert _Chain()._recommend_proxy("boom") is None


def test_resolve_proxy_url_still_honours_explicit_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``proxy=False`` short-circuits before the except can ever be reached."""
    monkeypatch.setenv("PRY_PROXY_URL", "http://env-proxy:8080")
    assert _Chain()._resolve_proxy_url({"proxy": False}) is None


def test_record_telemetry_failure_never_breaks_the_scrape() -> None:
    """Telemetry is observability-only; a dead backend must not raise."""

    def _boom(**_kw: object) -> None:
        raise RuntimeError("telemetry backend down")

    original = us._HAS_FALLBACK_TELEMETRY, us._record_fallback
    us._HAS_FALLBACK_TELEMETRY, us._record_fallback = True, _boom
    try:
        UltimateScraper()._record_telemetry(
            domain="example.com",
            tier_order=["direct"],
            attempts=[],
            final_tier=None,
            success=False,
            start=0.0,
            errors=["boom"],
        )
    finally:
        us._HAS_FALLBACK_TELEMETRY, us._record_fallback = original
