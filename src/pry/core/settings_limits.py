"""Pry — rate limiting / quota settings (split from settings.py).

Mixin holding rate limits, retry budgets, rotation timing, and sports-data
upstream quotas. Combined into `PrySettings` in `pry.core.settings`.

Pure code move — no config values or logic changed.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from pydantic import AliasChoices, Field


class LimitsSettings:
    """Rate limits, retry budgets, rotation timing, and upstream quotas."""

    # Rotation / retry (legacy env aliases)
    rotation_user_agent: str = "rotate"
    rotation_timing: str = "random"
    rotation_delay_range: tuple[float, float] = (0.5, 3.0)
    max_retries: int = Field(
        default=3,
        validation_alias=AliasChoices("PRY_MAX_RETRIES", "MAX_RETRIES"),
    )
    min_quality: int = Field(
        default=20,
        validation_alias=AliasChoices("PRY_MIN_QUALITY", "MIN_QUALITY"),
    )
    retry_backoff: str = "exponential"
    rate_limit_rpm: int = Field(
        default=120,
        validation_alias=AliasChoices("PRY_RATE_LIMIT_RPM", "RATE_LIMIT_RPM"),
    )

    # In-memory TTL for cached odds/stats/scores (seconds). Bots poll
    # sub-minute; a ~10s TTL collapses upstream calls ~6x and keeps reads
    # sub-100ms.
    sports_odds_cache_ttl_seconds: int = Field(default=10, ge=1)
    # Sustained upstream request budget for The Odds API (requests/min),
    # enforced by the sports_data.cache token-bucket rate limiter.
    sports_odds_rate_limit_rpm: int = Field(default=30, ge=1)
