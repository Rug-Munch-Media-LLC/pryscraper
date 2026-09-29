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

    def _build_tier_order(
        self, proxy_url: str | None, premium_first: bool
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

        # Premium proxy — the LAST paid resort, after Tor. Only added when it
        # was not already tried first above.
        if proxy_url and not premium_first:
            tier_order.append(("premium_proxy", self._tier_premium_proxy))

        # Tiers with persisted evidence of never winning are SKIPPED, and the
        # skip is reported rather than silently vanishing from the chain, so a
        # caller can tell "we did not try that" from "we tried and it failed".
        #
        # The cost is measured, not assumed: over 8 sources the committed
        # baseline recorded by_via {direct: 4, flaresolverr: 1}. archive,
        # google_cache and premium_proxy won ZERO, and archive/google_cache
        # appeared in 2 of 3 failures at 25-45s each — about 89% of the ladder's
        # wall clock went to rungs that never returned a result.
        #
        # should_skip() requires >=3 recorded attempts and ZERO wins ever: a tier
        # that has won once is kept, and one sample is not enough to condemn
        # either. See engine/tier_health.py.
        kept: list[tuple[str, Any]] = []
        skipped: list[str] = []
        for name, fn in tier_order:
            skip, reason = should_skip_tier(name)
            if skip:
                skipped.append(f"{name}:skipped({reason})")
                continue
            kept.append((name, fn))
        tier_order = kept
        self._last_skipped_tiers = skipped

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

        return tier_order
