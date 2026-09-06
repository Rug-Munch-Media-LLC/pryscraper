"""Pry — Ultimate Anti-Detection Scraper (facade).
Multi-strategy scraping with 10+ bypass methods and intelligent fallback.
Beats Cloudflare, DataDome, Akamai, Imperva, PerimeterX, and generic blocks.

The orchestration (``scrape()`` / fallback chain / retry configs) lives in
``pry.engine.scraper_orchestrate`` (mixed in via ``ScrapeOrchestrator``);
the concrete tier implementations live in ``pry.engine.tiers`` (mixed in via
``TierMixin``); the per-domain semaphore registry and the tier→breaker
mapping live in ``pry.engine.circuit_breaker``.

The availability flags and optional scraper singletons below stay on THIS
module (rather than ``scraper_orchestrate``) because tests patch them here
and tier methods resolve them lazily through ``tiers_base._us_flag``.
"""

# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).

from __future__ import annotations

import importlib.util

# ``time`` is unused here but must stay importable as a module attribute:
# tests freeze the clock via ``monkeypatch.setattr(ultimate_scraper.time, ...)``.
import time  # noqa: F401
from typing import Any

from pry.engine.browser_pool import (
    BrowserPool,
    close_browsers,
    get_browser_pool,
)
from pry.engine.resilience import registry  # noqa: F401  (tests patch/replace this)
from pry.engine.scraper_orchestrate import ScrapeOrchestrator

__all__ = ["BrowserPool", "UltimateScraper", "close_browsers", "get_browser_pool"]

# Try importing optional bypass libraries
_has_cloudscraper = importlib.util.find_spec("cloudscraper") is not None
_has_undetected = importlib.util.find_spec("undetected_chromedriver") is not None
_has_playwright = importlib.util.find_spec("playwright") is not None
_has_tor = importlib.util.find_spec("aiohttp_socks") is not None

TLSScraper: Any = None
_has_tls = True
try:
    from pry.engine.tls_fingerprint import TLSScraper
except ImportError:  # pragma: no cover - optional dependency
    _has_tls = False

CamoufoxBrowser: Any = None
_has_camoufox = True
try:
    from pry.engine.camoufox_integration import CamoufoxBrowser
except ImportError:  # pragma: no cover - optional dependency
    _has_camoufox = False

_stealth_engine: Any
try:
    from pry.engine.stealth_engine import StealthEngine

    _stealth_engine = StealthEngine()
except ImportError:
    _stealth_engine = None

# Optional block-detection + fallback-telemetry integration (guarded so the
# scraper still works if either module is unavailable at runtime).
_HAS_BLOCK_DETECTION = False
_block_detect: Any = None
try:
    import pry.engine.block_detection as _block_detection_mod

    _block_detect = _block_detection_mod.detect_block
    _HAS_BLOCK_DETECTION = True
except ImportError:  # pragma: no cover - optional dependency
    pass

_HAS_FALLBACK_TELEMETRY = False
_record_fallback: Any = None
try:
    from pry.engine.fallback_telemetry import record_fallback

    _record_fallback = record_fallback
    _HAS_FALLBACK_TELEMETRY = True
except ImportError:  # pragma: no cover - optional dependency
    pass

# Tiers 13-15: Advanced scraping methods
_ai_visual: Any = None
_has_ai_visual = True
try:
    from pry.engine.ai_visual_scraper import AIVisualScraper

    _ai_visual = AIVisualScraper()
except ImportError:
    _has_ai_visual = False

_mobile_scraper: Any = None
_has_mobile = True
try:
    from pry.engine.mobile_app_scraper import MobileAppScraper

    _mobile_scraper = MobileAppScraper()
except ImportError:
    _has_mobile = False

_graphql_scraper: Any = None
_has_graphql = True
try:
    from pry.engine.graphql_scraper_enhanced import GraphQLScraper

    _graphql_scraper = GraphQLScraper()
except ImportError:
    _has_graphql = False


# Process-level singleton browser pool. The pool itself lives in
# ``pry.engine.browser_pool``; this module re-exports the singleton instance
# (``_browser_pool``) and the ``close_browsers()`` shutdown hook for backward
# compatibility with callers/tests that import them from here. All
# ``UltimateScraper`` instances share this one pool via ``get_browser_pool()``.
_browser_pool = get_browser_pool()


class UltimateScraper(ScrapeOrchestrator):
    """15-tier anti-detection scraper with automatic fallback.

    Tiers (tried in this order by default):
    1. Direct HTTP (smart headers, rotating UAs)
    2. TLS fingerprint impersonation (curl_cffi JA3/JA4 bypass)
    3. cloudscraper (Python-native Cloudflare bypass)
    4. FlareSolverr (Cloudflare/WAF bypass service)
    5. undetected-chromedriver (modified Chrome, no detection)
    6. Camoufox stealth Firefox (source-level anti-fingerprinting)
    7. Playwright stealth (full browser with human behavior)
    8. Googlebot UA (search engine crawl mimic)
    9. Tor proxy (anonymous routing via SOCKS5 — mid-tier, before paid proxy)
    10. Premium proxy retry (paid last resort, after Tor)
    11. Archive.org / Wayback Machine (cached version)
    12. Google Cache (cached version — absolute last resort)
    13. AI Visual Scraper (screenshot + LLM vision extraction)
    14. Mobile App API (impersonate mobile clients)
    15. GraphQL API Discovery (find and query GraphQL endpoints)

    The per-domain order is adaptive: resilience.DomainTierMemory promotes
    the domain's proven-best tier to the front and demotes/skip tiers that
    have been failing, so each domain gets an intelligent, self-improving
    fallback chain.
    """

    def __init__(self) -> None:
        self._ua_index = 0
        self._tls_scraper = TLSScraper() if _has_tls else None
        self._camoufox = CamoufoxBrowser() if _has_camoufox else None
