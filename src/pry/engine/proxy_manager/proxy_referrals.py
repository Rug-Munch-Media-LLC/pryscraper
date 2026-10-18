"""Affiliate signup links, referral clicks and the proxy referral catalog.

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

from pry.engine.proxy_providers import (
    PREMIUM_PROXY_PROVIDERS,
    find_provider,
    get_proxy_referral,
    get_proxy_referral_summary,
    get_proxy_referral_url,
    list_proxy_referrals,
    parse_ts as _parse_ts,
)

logger = logging.getLogger(__name__)


class ProxyReferralMixin:
    """Signup/referral flow and the curated proxy referral catalog."""

    def get_signup_link(self, provider_tag: str = "") -> str:
        """Get the affiliate signup link for a provider. Records the click for revenue tracking."""
        if not provider_tag:
            provider_tag = "brightdata"
        provider = find_provider(provider_tag) or PREMIUM_PROXY_PROVIDERS[0]
        try:
            from pry.commerce.referrals import ReferralTracker

            tracker = ReferralTracker()
            tracker.record_click(
                provider["tag"],
                provider["signup_url"],
                source="proxy_manager",
                user_id=os.getenv("USER", ""),
            )
        except Exception as e:  # noqa: BLE001
            logger.debug("referral_track_failed", extra={"error": str(e)[:80]})
        return provider["signup_url"]

    def get_recommendation(self, last_error: str = "") -> dict[str, Any]:
        """Get a recommendation for which proxy provider to use.

        Returns: signup URL, estimated cost, why recommended.
        """
        if not self.needs_premium_proxy(last_error):
            return {"needs_premium": False, "message": "Free fallbacks sufficient"}
        provider = PREMIUM_PROXY_PROVIDERS[0]
        return {
            "needs_premium": True,
            "reason": f"Site appears blocked: '{last_error[:80]}'",
            "recommended_provider": provider["name"],
            "signup_url": self.get_signup_link(provider["tag"]),
            "estimated_cost": provider["min_price"],
            "free_trial": provider.get("free_trial", "Unknown"),
            "all_providers": PREMIUM_PROXY_PROVIDERS[:3],
        }

    def record_referral_click(self, provider_tag: str, user_id: str = "") -> str:
        """Record a referral click for a specific provider. Returns the click_id."""
        provider = find_provider(provider_tag)
        if not provider:
            return ""
        try:
            from pry.commerce.referrals import ReferralTracker

            tracker = ReferralTracker()
            return tracker.record_click(
                provider["tag"],
                provider["signup_url"],
                source="proxy_signup",
                user_id=user_id,
            )
        except Exception as e:  # noqa: BLE001
            logger.debug("referral_record_failed", extra={"error": str(e)[:80]})
        return ""

    def get_recent_clicks(self, days_back: int = 30) -> list[dict[str, Any]]:
        """Get recent proxy referral clicks for revenue tracking."""
        try:
            from pry.commerce.referrals import ReferralTracker

            tracker = ReferralTracker()
            cutoff = datetime.now(UTC).timestamp() - (days_back * 86400)
            return [
                c
                for c in tracker.clicks  # type: ignore[attr-defined]  # ReferralTracker.clicks is loaded dynamically from DB
                if c.get("source", "").startswith("proxy")
                and _parse_ts(c.get("timestamp", "")) >= cutoff
            ]
        except Exception as e:  # noqa: BLE001
            logger.debug("recent_clicks_failed", extra={"error": str(e)[:80]})
            return []

    def get_proxy_referral(self, provider_tag: str) -> dict[str, Any]:
        """Get the curated referral info for a proxy provider (see proxy_providers)."""
        return get_proxy_referral(provider_tag)

    def get_proxy_referral_url(self, provider_tag: str) -> str:
        """Get just the referral URL for a proxy provider."""
        return get_proxy_referral_url(provider_tag)

    def list_proxy_referrals(self) -> list[dict[str, Any]]:
        """List all proxy provider referrals (curated, marketing-friendly view)."""
        return list_proxy_referrals()

    def get_proxy_referral_summary(self) -> dict[str, Any]:
        """Return a per-tier summary of proxy referrals."""
        return get_proxy_referral_summary()


__all__ = ["ProxyReferralMixin"]
