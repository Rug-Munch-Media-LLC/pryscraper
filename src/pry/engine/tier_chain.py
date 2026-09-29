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

