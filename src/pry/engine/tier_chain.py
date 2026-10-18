"""Where the request goes, and in what order the tiers are tried.

Extracted from ``pry.engine.scraper_orchestrate`` as a mixin: proxy
resolution (explicit option -> ProxyManager -> env) and the fallback-chain
builder (trusted cheap tiers -> Tor -> premium -> cached) are both
pre-flight decisions — the chain is fixed before the first attempt runs.
:class:`pry.engine.scraper_orchestrate.ScrapeOrchestrator` inherits
:class:`TierChainMixin`, so ``scraper._resolve_proxy_url(...)``,
``scraper._recommend_proxy(...)`` and ``scraper._build_tier_order(...)`` are
unchanged.
"""

# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).

from __future__ import annotations

import logging
import os
from typing import Any, ClassVar

from pry.engine.tier_health import should_skip as should_skip_tier
from pry.engine.tiers_base import _us_flag

logger = logging.getLogger(__name__)


class TierChainMixin:
    """Proxy target resolution + fallback-chain construction."""

    def _resolve_proxy_url(self, opts: dict[str, Any]) -> str | None:
        """Resolve the configured proxy URL from options, ProxyManager, or env."""
        if opts.get("proxy_url"):
            return opts["proxy_url"]
        if opts.get("proxy") is False:
            return None
        try:
            from pry.engine.proxy_manager import ProxyManager

            pm = ProxyManager()
            return pm.get_proxy_url()
        except Exception as e:  # noqa: BLE001
            logger.debug("proxy_resolve_failed", extra={"error": str(e)[:80]})
        env_url = os.getenv("PRY_PROXY_URL") or os.getenv("PROXY_URL")
        return env_url or None

    def _recommend_proxy(self, last_error: str) -> dict[str, Any] | None:
        """Build a proxy recommendation for the response when scraping fails."""
        try:
            from pry.engine.proxy_manager import ProxyManager

            return ProxyManager().get_recommendation(last_error)
        except Exception as e:  # noqa: BLE001
            logger.debug("proxy_recommend_failed", extra={"error": str(e)[:80]})
            return None

    #: Tier skips from the most recent _build_tier_order call, for reporting.
    #: ClassVar because the mixin is mixed in, not constructed per instance;
    #: ruff RUF012 is right that a bare mutable list default would be shared.
    _last_skipped_tiers: ClassVar[list[str]] = []

    #: Availability flag each optional tier depends on. A tier returning None
    #: because its flag is off never ran; a loss would poison it forever.
    _UNAVAILABLE_FLAGS: ClassVar[dict[str, str]] = {
        "tls_fingerprint": "_has_tls",
        "cloudscraper": "_has_cloudscraper",
        "undetected": "_has_undetected",
        "playwright": "_has_playwright",
        "camoufox": "_has_camoufox",
        "tor": "_has_tor",
        "ai_visual": "_has_ai_visual",
        "mobile_app": "_has_mobile",
        "graphql": "_has_graphql",
    }

    def _tier_unavailable(self, tier_name: str) -> bool:
        """True when the tier cannot run at all because a dependency is missing."""
        flag = self._UNAVAILABLE_FLAGS.get(tier_name)
        if flag:
            try:
                return not bool(_us_flag(flag))
            except (AttributeError, ImportError):
                return False
        if tier_name == "flaresolverr":
            try:
                from pry.core.settings import settings

                return not bool(settings.flaresolverr_url)
            except (AttributeError, ImportError):
                return False
        return False

    def _ladder_budget(self, tier_count: int) -> tuple[float, float]:
        """Return ``(per_tier_deadline_s, ladder_budget_s)``.

        The old fixed 45 s cap was shorter than ONE Tor attempt, so a slow
        early rung consumed the whole ladder and tiers 9-15 never ran. The
        budget is now the sum of the per-tier deadlines the ladder may still
        spend: a fast failure at the top leaves the full time for the rest,
        and no single rung can eat more than its own deadline.
        """
        per_tier = float(os.getenv("PRY_TIER_TIMEOUT_S", "45") or 45)
        total = float(os.getenv("PRY_LADDER_BUDGET_S", "0") or 0)
        if total <= 0:
            total = per_tier * max(1, tier_count)
        return per_tier, total

    def _build_tier_order(
        self, proxy_url: str | None, premium_first: bool, domain: str | None = None
    ) -> list[tuple[str, Any]]:
        """Build the fallback chain (cheap tiers -> Tor -> premium -> cached).

        Note: ``_tier_premium_proxy`` has signature (url, proxy_url, opts)
        while other tiers use (url, opts, proxy_url) — handled at the call
        site in :meth:`_attempt_tier`.
        """
        tier_order: list[tuple[str, Any]] = [
            ("direct", self._tier_direct),
            ("tls_fingerprint", self._tier_tls_fingerprint),
            ("cloudscraper", self._tier_cloudscraper),
            ("flaresolverr", self._tier_flaresolverr),
            ("undetected", self._tier_undetected),
            ("camoufox", self._tier_camoufox),
            ("playwright", self._tier_playwright),
            ("googlebot", self._tier_googlebot),
            # Tor mid-chain: anonymous fallback tried before we pay for a
            # premium proxy, but after the trusted cheap methods.
            ("tor", self._tier_tor),
        ]

        # Premium proxy — NO LONGER last. Measured 2026-08-29, deployed container:
        #   theblock.co    plain curl      403, 5 KB
        #                   full 12-tier chain, 100s budget   FAILED, verdict=blocked
        #                   premium_proxy   744,148 B in 324ms
        # It is not slow and not broken: it was buried under ten rungs that each
        # burn 10-45s, so it was never REACHED. So it moves to position 2, after
        # direct (free, sub-second). Set PRY_PROXY_AFTER_TIERS to pin it back.
        if proxy_url and not premium_first and not os.getenv("PRY_PROXY_AFTER_TIERS"):
            tier_order.insert(1, ("premium_proxy", self._tier_premium_proxy))
        elif proxy_url and not premium_first:
            tier_order.append(("premium_proxy", self._tier_premium_proxy))

        # Tiers with persisted evidence of never winning on THIS domain are
        # SKIPPED, and the skip is reported rather than silently vanishing.
        # should_skip() requires >=3 executed attempts and ZERO wins: a tier
        # that has won once is kept. See engine/tier_health.py.

        tier_order.extend(
            [
                ("archive", self._tier_archive),
                ("google_cache", self._tier_google_cache),
            ]
        )

        # Tier 13: AI Visual Scraper (screenshot + LLM vision)
        ai_visual = _us_flag("_ai_visual")
        if _us_flag("_has_ai_visual") and ai_visual and ai_visual.is_available():
            tier_order.append(("ai_visual", self._tier_ai_visual))

        # Tier 14: Mobile App API Scraper
        if _us_flag("_has_mobile") and _us_flag("_mobile_scraper"):
            tier_order.append(("mobile_app", self._tier_mobile_app))

        # Tier 15: GraphQL API Discovery
        if _us_flag("_has_graphql") and _us_flag("_graphql_scraper"):
            tier_order.append(("graphql", self._tier_graphql))

        # Skip-on-observed-zero-win runs HERE, at the end, not earlier.
        # It was originally placed before the archive/google_cache/ai_visual
        # appends, so those tiers were added AFTER the filter and could never be
        # skipped no matter how many losses they accrued. Measured in the
        # deployed container: google_cache, mobile_app and graphql each had 4
        # attempts, 0 wins and ~3s wasted, and were still in the chain, while
        # camoufox (which IS in the initial list) was correctly skipped. A
        # filter placed before the list is finished filtering half a list.
        kept: list[tuple[str, Any]] = []
        skipped: list[str] = []
        for name, fn in tier_order:
            # Domain-scoped: a tier that never won on domain A is not thereby
            # condemned on domain B. With domain=None the legacy unscoped keys
            # are read, which is what the status tooling and its tests use.
            skip, reason = should_skip_tier(name, domain=domain)
            if skip:
                skipped.append(f"{name}:skipped({reason})")
                continue
            kept.append((name, fn))
        tier_order = kept
        self._last_skipped_tiers = skipped

        return tier_order
