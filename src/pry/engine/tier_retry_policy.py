"""Retry configuration and block-signal escalation policy for the tier chain.

Extracted from ``pry.engine.scraper_orchestrate`` as a mixin so the per-tier
retry table and the "which tier family to try next after this block" mapping
live in one place. :class:`pry.engine.scraper_orchestrate.ScrapeOrchestrator`
inherits :class:`TierRetryPolicyMixin`, so every existing attribute access
(``scraper._RETRY_CONFIGS``, ``scraper._PREFER_ON_BLOCK``) is unchanged.
"""

# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).

from __future__ import annotations

from typing import Any, ClassVar

from pry.engine.retry import Jitter, RetryConfig


class TierRetryPolicyMixin:
    """Per-tier retry budgets and block-signal tier preferences."""

    # Per-tier retry configurations for transient failure resilience.
    # Browser-based tiers (undetected, camoufox, playwright) use 0 retries
    # because launching a browser is expensive; network-only tiers retry 1-2x.
    _RETRY_CONFIGS: ClassVar[dict[str, RetryConfig]] = {
        "direct": RetryConfig(max_retries=2, base_delay=0.5, max_delay=5.0),
        "tls_fingerprint": RetryConfig(max_retries=1, base_delay=1.0, max_delay=5.0),
        # A dead target needs no de-synchronisation: jitter only spreads
        # retries of a URL that may work. Cap and retry shape unchanged.
        "cloudscraper": RetryConfig(
            max_retries=1, base_delay=1.0, max_delay=5.0, jitter=Jitter.NONE
        ),
        "flaresolverr": RetryConfig(
            max_retries=2, base_delay=2.0, max_delay=10.0, jitter=Jitter.NONE
        ),
        "undetected": RetryConfig(max_retries=0),
        "camoufox": RetryConfig(max_retries=0),
        "playwright": RetryConfig(max_retries=0),
        "googlebot": RetryConfig(max_retries=2, base_delay=0.5, max_delay=5.0),
        "premium_proxy": RetryConfig(max_retries=2, base_delay=1.0, max_delay=8.0),
        "archive": RetryConfig(max_retries=2, base_delay=0.5, max_delay=5.0),
        "google_cache": RetryConfig(max_retries=2, base_delay=0.5, max_delay=5.0),
        "tor": RetryConfig(max_retries=1, base_delay=2.0, max_delay=10.0),
        "ai_visual": RetryConfig(max_retries=0),
        "mobile_app": RetryConfig(max_retries=1, base_delay=1.0, max_delay=5.0),
        "graphql": RetryConfig(max_retries=1, base_delay=1.0, max_delay=5.0),
    }
    _DEFAULT_RETRY: ClassVar[RetryConfig] = RetryConfig(max_retries=1, base_delay=1.0)

    # Block kinds from block_detection.detect_block mapped to the tier names
    # that should be preferred NEXT in the fallback chain. "rate_limited" is
    # intentionally absent: backoff is already handled by the per-tier retry
    # configs above.
    _PREFER_ON_BLOCK: ClassVar[dict[str, tuple[str, ...]]] = {
        "cloudflare": ("flaresolverr", "cloudscraper", "undetected", "camoufox", "playwright"),
        "captcha": ("undetected", "camoufox", "playwright", "flaresolverr"),
        "js_required": ("playwright", "camoufox", "undetected"),
        "access_denied": ("tor", "premium_proxy"),
    }

    def _promote_preferred_tiers(
        self, tier_order: list[tuple[str, Any]], i: int, kind: str
    ) -> None:
        """Promote the preferred tier family for a detected block signal (in place)."""
        preferred = self._PREFER_ON_BLOCK.get(kind, ())
        if preferred and i + 1 < len(tier_order):
            remaining = tier_order[i + 1 :]
            preferred_tiers = [t for t in remaining if t[0] in preferred]
            if preferred_tiers:
                tier_order[i + 1 :] = preferred_tiers + [
                    t for t in remaining if t[0] not in preferred
                ]
