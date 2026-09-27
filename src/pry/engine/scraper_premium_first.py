"""Premium-proxy-first scrape path (opt-in rung 0 of the fallback chain).

Extracted from ``pry.engine.scraper_orchestrate`` as a mixin so the paid
first-attempt path owns itself. :class:`pry.engine.scraper_orchestrate.ScrapeOrchestrator`
inherits :class:`PremiumFirstMixin`, so ``scraper._premium_first(...)`` and
``use_premium_proxy_first`` behave exactly as before.
"""

# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).

from __future__ import annotations

import time
from typing import Any


class PremiumFirstMixin:
    """The opt-in "try the paid proxy before anything free" rung."""

    async def _premium_first(
        self,
        *,
        url: str,
        proxy_url: str,
        opts: dict[str, Any],
        domain: str,
        scrape_start: float,
        attempts: list[dict[str, Any]],
        errors: list[str],
        latest_signal: dict[str, Any] | None,
        registry: Any = None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Run the premium-proxy-first attempt when the caller requested it.

        Returns ``(result, latest_signal)`` — result is None when the premium
        attempt failed (caller proceeds with the regular chain).
        """
        start = time.time()
        html = await self._tier_premium_proxy(url, proxy_url, opts)
        latency = time.time() - start
        signal = self._detect_block_signal(html)
        success = bool(html and self._is_valid(html))
        block_kind = ""
        if signal is not None and signal.kind != "none":
            latest_signal = self._signal_to_dict(signal)
            success = False
            block_kind = signal.kind
        # The paid rung must be learnable too: without this the most
        # expensive tier in the ladder has no memory at all and the ranking
        # can neither promote it when it works nor demote it when it fails.
        if registry is not None:
            self._record_tier_outcome(
                registry,
                None,
                domain,
                "premium_proxy",
                success,
                latency,
                block_kind=block_kind,
            )
        if success:
            assert isinstance(html, str)
            attempts.append(
                {
                    "tier": "premium_proxy",
                    "success": True,
                    "error": None,
                    "duration_ms": round(latency * 1000, 2),
                }
            )
            self._record_telemetry(
                domain, ["premium_proxy"], attempts, "premium_proxy", True, scrape_start, errors
            )
            return self._result(
                url, html, "premium_proxy", block_signal=latest_signal
            ), latest_signal
        errors.append("premium_proxy_failed")
        attempts.append(
            {
                "tier": "premium_proxy",
                "success": False,
                "error": "premium_proxy_failed",
                "duration_ms": round(latency * 1000, 2),
            }
        )
        return None, latest_signal
