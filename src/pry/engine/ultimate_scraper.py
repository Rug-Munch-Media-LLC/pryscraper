"""Pry — Ultimate Anti-Detection Scraper.
Multi-strategy scraping with 10+ bypass methods and intelligent fallback.
Beats Cloudflare, DataDome, Akamai, Imperva, PerimeterX, and generic blocks.

The concrete tier implementations live in ``pry.engine.tiers`` (mixed in via
``TierMixin``); the per-domain semaphore registry and the tier→breaker
mapping live in ``pry.engine.circuit_breaker``.
"""

# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import time
from typing import Any, ClassVar
from urllib.parse import urlparse

from pry.core.errors import InvalidRequestError
from pry.core.observability import SCRAPE_LATENCY, span
from pry.engine.browser_pool import (
    BrowserPool,
    close_browsers,
    get_browser_pool,
)
from pry.engine.circuit_breaker import BREAKER_FOR_TIER, domain_semaphore
from pry.engine.resilience import registry
from pry.engine.retry import RetryConfig, async_retry
from pry.engine.tiers import TierMixin
from pry.engine.url_guard import validate_url

__all__ = ["BrowserPool", "UltimateScraper", "close_browsers", "get_browser_pool"]

logger = logging.getLogger(__name__)

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


class UltimateScraper(TierMixin):
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

    USER_AGENTS: ClassVar[list[str]] = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    ]

    def __init__(self) -> None:
        self._ua_index = 0
        self._tls_scraper = TLSScraper() if _has_tls else None
        self._camoufox = CamoufoxBrowser() if _has_camoufox else None

    # Per-tier retry configurations for transient failure resilience.
    # Browser-based tiers (undetected, camoufox, playwright) use 0 retries
    # because launching a browser is expensive; network-only tiers retry 1-2x.
    _RETRY_CONFIGS: ClassVar[dict[str, RetryConfig]] = {
        "direct": RetryConfig(max_retries=2, base_delay=0.5, max_delay=5.0),
        "tls_fingerprint": RetryConfig(max_retries=1, base_delay=1.0, max_delay=5.0),
        "cloudscraper": RetryConfig(max_retries=1, base_delay=1.0, max_delay=5.0),
        "flaresolverr": RetryConfig(max_retries=2, base_delay=2.0, max_delay=10.0),
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

    async def scrape(self, url: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        """Scrape any URL with automatic bypass strategy selection.

        Thin public entry: emits the ``scrape.request`` parent span (with
        final method/success attributes) around ``_scrape_with_fallbacks``,
        which tries up to 10 strategies until one succeeds.

        Per-domain concurrency throttle: at most
        ``circuit_breaker.DOMAIN_MAX_CONCURRENCY`` scrapes may run against the
        same domain at once. This prevents a single caller (or a burst of
        callers) from hammering one target site with unbounded parallel
        requests — an abuse vector that would get the target (and our egress
        IPs) rate-limited or banned. Different domains proceed in parallel;
        only same-domain concurrency is bounded.
        """
        parsed = urlparse(url)
        domain = parsed.netloc or "unknown"
        sem = domain_semaphore(domain)
        async with sem:
            with span("scrape.request", {"http.url": url}) as request_span:
                result = await self._scrape_with_fallbacks(url, options)
                if request_span is not None and isinstance(result, dict):
                    request_span.set_attribute("pry.method", str(result.get("method", "")))
                    request_span.set_attribute("pry.success", result.get("status") == "success")
                    if isinstance(result.get("attempts"), list):
                        request_span.set_attribute("pry.attempts", len(result["attempts"]))
                return result

    async def _scrape_with_fallbacks(
        self, url: str, options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Fallback-chain implementation (tier order, block detection, retries)."""
        opts = options or {}
        errors: list[str] = []
        try:
            validate_url(url)
        except InvalidRequestError as e:
            return {"status": "error", "url": url, "error": str(e)}

        proxy_url = self._resolve_proxy_url(opts)
        parsed = urlparse(url)
        domain = parsed.netloc
        scrape_start = time.time()
        attempts: list[dict[str, Any]] = []
        latest_signal: dict[str, Any] | None = None

        # Tier 0: Premium proxy — only first if the caller explicitly asks.
        # Default is False: paid proxy is a LAST resort, tried after Tor.
        premium_first = opts.get("use_premium_proxy_first", False)
        if proxy_url and premium_first:
            start = time.time()
            html = await self._tier_premium_proxy(url, proxy_url, opts)
            latency = time.time() - start
            signal = self._detect_block_signal(html)
            success = bool(html and self._is_valid(html))
            if signal is not None and signal.kind != "none":
                latest_signal = self._signal_to_dict(signal)
                success = False
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
                return self._result(url, html, "premium_proxy", block_signal=latest_signal)
            errors.append("premium_proxy_failed")
            attempts.append(
                {
                    "tier": "premium_proxy",
                    "success": False,
                    "error": "premium_proxy_failed",
                    "duration_ms": round(latency * 1000, 2),
                }
            )

        # Build tier list. Trusted cheap tiers first, then Tor (anonymous,
        # free), then the paid premium proxy LAST, then cached-version
        # fallbacks as the absolute last resort.
        # Note: _tier_premium_proxy has signature (url, proxy_url, opts) while
        # other tiers use (url, opts, proxy_url). This is handled at call site.
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

        tier_order.extend(
            [
                ("archive", self._tier_archive),
                ("google_cache", self._tier_google_cache),
            ]
        )

        # Tier 13: AI Visual Scraper (screenshot + LLM vision)
        if _has_ai_visual and _ai_visual and _ai_visual.is_available():
            tier_order.append(("ai_visual", self._tier_ai_visual))

        # Tier 14: Mobile App API Scraper
        if _has_mobile and _mobile_scraper:
            tier_order.append(("mobile_app", self._tier_mobile_app))

        # Tier 15: GraphQL API Discovery
        if _has_graphql and _graphql_scraper:
            tier_order.append(("graphql", self._tier_graphql))

        # Adaptive ordering: promote the domain's proven-best tier to the
        # front and demote/skip tiers that have been failing recently. Each
        # domain gets an intelligent, self-improving fallback chain.
        name_to_fn = dict(tier_order)
        ordered_names = registry.reorder_for_domain(domain, [name for name, _ in tier_order])
        tier_order = [(name, name_to_fn[name]) for name in ordered_names]

        i = 0
        try:
            async with asyncio.timeout(45):
                while i < len(tier_order):
                    tier_name, tier_fn = tier_order[i]
                    # Skip external tiers whose circuit breaker is open.
                    breaker_name = BREAKER_FOR_TIER.get(tier_name)
                    if breaker_name and not registry.is_service_allowed(breaker_name):
                        logger.debug(
                            "tier_skipped_circuit_open", extra={"tier": tier_name, "domain": domain}
                        )
                        errors.append(f"{tier_name}: circuit_open")
                        i += 1
                        continue

                    start = time.time()
                    try:
                        retry_cfg = self._RETRY_CONFIGS.get(tier_name, self._DEFAULT_RETRY)
                        # Child span per tier attempt — the trace shows exactly which
                        # bypass strategies a target needed and what each cost.
                        with span("scrape.tier", {"pry.tier": tier_name, "http.url": url}):
                            if tier_name == "premium_proxy":
                                html = await async_retry(
                                    tier_fn, url, proxy_url, opts, config=retry_cfg
                                )
                            else:
                                html = await async_retry(
                                    tier_fn, url, opts, proxy_url=proxy_url, config=retry_cfg
                                )
                    except InvalidRequestError:
                        # SSRF rejection (e.g. redirect to a private/metadata IP) is not a
                        # tier failure — abort the whole chain instead of falling through
                        # to other tiers that would hit the same unsafe target.
                        raise
                    except Exception as e:
                        logger.debug(
                            "tier_exception", extra={"tier": tier_name, "error": str(e)[:200]}
                        )
                        html = None

                    latency = time.time() - start

                    # Block detection: classify the tier response (or failure) so the
                    # next tier choice can escalate intelligently. Tiers expose only the
                    # body, so status/headers default to 200/{} — body markers drive the
                    # classification. A block page is not content: even if it passes
                    # _is_valid (e.g. a long WAF challenge), it does not count as success
                    # and the chain escalates to the preferred tier family.
                    signal = self._detect_block_signal(html)
                    success = bool(html and self._is_valid(html))
                    if signal is not None and signal.kind != "none":
                        latest_signal = self._signal_to_dict(signal)
                        preferred = self._PREFER_ON_BLOCK.get(signal.kind, ())
                        if preferred and i + 1 < len(tier_order):
                            remaining = tier_order[i + 1 :]
                            preferred_tiers = [t for t in remaining if t[0] in preferred]
                            if preferred_tiers:
                                tier_order[i + 1 :] = preferred_tiers + [
                                    t for t in remaining if t[0] not in preferred
                                ]
                        success = False

                    registry.record_domain_tier_result(domain, tier_name, success, latency)
                    if breaker_name:
                        registry.record_service_result(breaker_name, success)
                    if SCRAPE_LATENCY:
                        SCRAPE_LATENCY.labels(method=tier_name).observe(latency)

                    if success:
                        method = "premium_proxy" if tier_name == "premium_proxy" else tier_name
                        if not isinstance(html, str):
                            continue
                        attempts.append(
                            {
                                "tier": tier_name,
                                "success": True,
                                "error": None,
                                "duration_ms": round(latency * 1000, 2),
                            }
                        )
                        self._record_telemetry(
                            domain, ordered_names, attempts, method, True, scrape_start, errors
                        )
                        return self._result(url, html, method, block_signal=latest_signal)
                    errors.append(f"{tier_name}_failed")
                    attempts.append(
                        {
                            "tier": tier_name,
                            "success": False,
                            "error": f"{tier_name}_failed",
                            "duration_ms": round(latency * 1000, 2),
                        }
                    )
                    i += 1
        except TimeoutError:
            errors.append("timeout_45s")

        self._record_telemetry(domain, ordered_names, attempts, None, False, scrape_start, errors)
        last_err = errors[-1] if errors else "all_tiers_failed"
        result: dict[str, Any] = {
            "status": "error",
            "url": url,
            "error": "; ".join(errors[-5:]) if errors else last_err,
            "content": "",
            "proxy_recommendation": self._recommend_proxy(last_err),
        }
        if latest_signal is not None:
            result["block_signal"] = latest_signal
        return result

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
        except Exception as e:
            logger.debug("proxy_resolve_failed", extra={"error": str(e)[:80]})
        env_url = os.getenv("PRY_PROXY_URL") or os.getenv("PROXY_URL")
        return env_url or None

    def _recommend_proxy(self, last_error: str) -> dict[str, Any] | None:
        """Build a proxy recommendation for the response when scraping fails."""
        try:
            from pry.engine.proxy_manager import ProxyManager

            return ProxyManager().get_recommendation(last_error)
        except Exception as e:
            logger.debug("proxy_recommend_failed", extra={"error": str(e)[:80]})
            return None

    def _result(
        self,
        url: str,
        html: str,
        method: str,
        block_signal: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": "ok",
            "url": url,
            "raw_html": html,
            "method": method,
            "content": self._extract_text(html),
        }
        if block_signal is not None:
            result["block_signal"] = block_signal
        return result
