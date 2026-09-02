"""Pry — Ultimate Anti-Detection Scraper.
Multi-strategy scraping with 10+ bypass methods and intelligent fallback.
Beats Cloudflare, DataDome, Akamai, Imperva, PerimeterX, and generic blocks."""

# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).

from __future__ import annotations

import importlib.util
import logging
import os
import random
import re
import threading
import time
from typing import Any, ClassVar
from urllib.parse import quote, urlparse

# SystemRandom: crypto-grade entropy so stealth jitter is not predictable.
import httpx

from pry.core.errors import InvalidRequestError
from pry.core.observability import SCRAPE_LATENCY, span
from pry.engine.browser_pool import (  # noqa: F401  (re-exported for backward compat)
    BrowserPool,
    close_browsers,
    get_browser_pool,
)
from pry.engine.resilience import registry
from pry.engine.retry import RetryConfig, async_retry
from pry.engine.url_guard import safe_get, validate_url

_RNG = random.SystemRandom()

logger = logging.getLogger(__name__)

# Per-domain concurrency throttle: cap the number of simultaneous scrapes to
# the SAME domain so a single caller (or a burst of callers) cannot hammer one
# target site with unbounded parallel requests. This protects both the target
# site (good citizenship / avoiding IP bans) and our own outbound resources.
# The limit is per-domain, not global — different domains proceed in parallel.
_DOMAIN_MAX_CONCURRENCY = 10
_domain_semaphores: dict[str, Any] = {}
_domain_semaphores_lock = threading.Lock()


def _domain_semaphore(domain: str) -> Any:
    """Return a per-domain asyncio.Semaphore, creating it on first use.

    Thread-safe creation (the semaphore registry is shared across the event
    loop and any worker threads). asyncio.Semaphore is not thread-safe to
    create concurrently, so creation is serialized under a lock.
    """
    with _domain_semaphores_lock:
        sem = _domain_semaphores.get(domain)
        if sem is None:
            import asyncio

            sem = asyncio.Semaphore(_DOMAIN_MAX_CONCURRENCY)
            _domain_semaphores[domain] = sem
        return sem


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

_stealth_engine: StealthEngine | None
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
    from pry.engine.block_detection import detect_block as _block_detect

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


async def _get_shared_client() -> httpx.AsyncClient:
    """Lazy import to avoid engine→api boundary violation (import-linter)."""
    from pry.core.client import get_client

    return await get_client()


# Process-level singleton browser pool. The pool itself lives in
# ``pry.engine.browser_pool``; this module re-exports the singleton instance
# (``_browser_pool``) and the ``close_browsers()`` shutdown hook for backward
# compatibility with callers/tests that import them from here. All
# ``UltimateScraper`` instances share this one pool via ``get_browser_pool()``.
_browser_pool = get_browser_pool()


class UltimateScraper:
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

    def _rotate_ua(self) -> str:
        ua = self.USER_AGENTS[self._ua_index % len(self.USER_AGENTS)]
        self._ua_index += 1
        return ua

    def _build_headers(self, url: str) -> dict[str, str]:
        parsed = urlparse(url)
        return {
            "User-Agent": self._rotate_ua(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": _RNG.choice(["en-US,en;q=0.9", "en-GB,en;q=0.8", "en-US,en;q=0.7"]),
            "Referer": f"https://{parsed.netloc}/",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        }

    async def scrape(self, url: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        """Scrape any URL with automatic bypass strategy selection.

        Thin public entry: emits the ``scrape.request`` parent span (with
        final method/success attributes) around ``_scrape_with_fallbacks``,
        which tries up to 10 strategies until one succeeds.

        Per-domain concurrency throttle: at most ``_DOMAIN_MAX_CONCURRENCY``
        scrapes may run against the same domain at once. This prevents a
        single caller (or a burst of callers) from hammering one target site
        with unbounded parallel requests — an abuse vector that would get the
        target (and our egress IPs) rate-limited or banned. Different domains
        proceed in parallel; only same-domain concurrency is bounded.
        """
        parsed = urlparse(url)
        domain = parsed.netloc or "unknown"
        sem = _domain_semaphore(domain)
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

        # External service tiers protected by circuit breakers.
        breaker_for_tier = {
            "flaresolverr": "flaresolverr",
            "playwright": "playwright",
            "camoufox": "camoufox",
            "tls_fingerprint": "tls_fingerprint",
        }

        i = 0
        while i < len(tier_order):
            tier_name, tier_fn = tier_order[i]
            # Skip external tiers whose circuit breaker is open.
            breaker_name = breaker_for_tier.get(tier_name)
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
                        html = await async_retry(tier_fn, url, proxy_url, opts, config=retry_cfg)
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
                logger.debug("tier_exception", extra={"tier": tier_name, "error": str(e)[:50]})
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
                assert isinstance(html, str)
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

    @staticmethod
    def _signal_to_dict(signal: Any) -> dict[str, Any]:
        """Convert a BlockSignal dataclass into a JSON-safe dict."""
        return {
            "kind": signal.kind,
            "confidence": signal.confidence,
            "recommended_escalation": signal.recommended_escalation,
            "evidence": list(signal.evidence),
        }

    def _detect_block_signal(self, html: str | None) -> Any:
        """Run block detection on a tier response; ``None`` when unavailable.

        Tiers expose only the body, so status/headers default to ``200``/``{}``
        and body markers drive the classification. A failed tier (``html is
        None``) yields an empty-body ``none`` signal — harmless, and it keeps
        the detect-on-every-attempt contract explicit.
        """
        if not _HAS_BLOCK_DETECTION:
            return None
        if html is not None:
            return _block_detect(html, 200, {})
        return _block_detect("", 0, {})

    def _record_telemetry(
        self,
        domain: str,
        tier_order: list[str],
        attempts: list[dict[str, Any]],
        final_tier: str | None,
        success: bool,
        start: float,
        errors: list[str],
    ) -> None:
        """Record the fallback journey via fallback_telemetry (best-effort).

        Never raises: telemetry is observability, not a correctness path.
        """
        if not _HAS_FALLBACK_TELEMETRY:
            return
        try:
            _record_fallback(
                domain=domain,
                tier_order=tier_order,
                attempts=attempts,
                final_tier=final_tier,
                success=success,
                duration_ms=round((time.time() - start) * 1000, 2),
                error="; ".join(errors[-5:]) if (errors and not success) else None,
            )
        except Exception:
            logger.debug("fallback_telemetry_record_failed", exc_info=True)

    def _is_valid(self, html: str | None) -> bool:
        if not html or len(html) < 500:
            return False
        lower = html.lower()
        block_indicators = [
            "cloudflare",
            "attention required",
            "just a moment",
            "enable javascript",
            "verify you are human",
        ]
        if any(i in lower for i in block_indicators) and len(html) < 5000:
            return False
        body = re.search(r"<body[^>]*>(.*?)</body>", html, re.DOTALL)
        if body:
            text = re.sub(r"<[^>]+>", " ", body.group(1)).strip()
            if len(text) < 50:
                return False
        return True

    def _extract_text(self, html: str) -> str:
        """Extract readable text from HTML."""
        try:
            from trafilatura import extract

            content = extract(
                html, output_format="markdown", include_links=True, include_images=False
            )
            if content and len(content) > 100:
                return content
        except Exception:  # noqa: S110 - fallback: try the next extractor
            pass
        try:
            from readability import Document

            doc = Document(html)
            content = doc.summary()
            if content and len(content) > 100:
                from markdownify import markdownify

                return markdownify(content, heading_arrows=False, strip=["script", "style"])  # type: ignore[call-arg]  # markdownify supports heading_arrows at runtime
        except Exception:  # noqa: S110 - fallback: strip tags as last resort
            pass
        # Last resort: strip HTML tags
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:50000] if len(text) > 50000 else text

    async def _tier_direct(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        try:
            # Proxy is a client-level httpx config (not a per-request param), so
            # a dedicated client is required only when a proxy is in play. The
            # common no-proxy path reuses the shared pooled client (get_client)
            # so connections are kept alive across requests.
            if proxy_url:
                async with httpx.AsyncClient(timeout=30, proxy=proxy_url) as c:
                    r = await safe_get(c, url, headers=self._build_headers(url))
            else:
                c = await _get_shared_client()
                r = await safe_get(c, url, headers=self._build_headers(url), timeout=30)
            if r.is_success:
                return r.text
        except (httpx.HTTPError, httpx.RequestError) as e:
            logger.debug("direct_failed", extra={"error": str(e)[:50]})
        return None

    async def _tier_premium_proxy(
        self, url: str, proxy_url: str, opts: dict[str, Any]
    ) -> str | None:
        """Fetch via the configured premium residential/datacenter proxy."""
        try:
            # This tier exists solely to route through the premium proxy, and
            # proxy is a client-level httpx config (not a per-request param).
            # A dedicated client is therefore required here — the shared pooled
            # client cannot carry a per-request proxy.
            async with httpx.AsyncClient(timeout=45, proxy=proxy_url) as c:
                r = await safe_get(c, url, headers=self._build_headers(url))
                if r.is_success:
                    return r.text
        except (httpx.HTTPError, httpx.RequestError) as e:
            logger.debug("premium_proxy_failed", extra={"error": str(e)[:50]})
        return None

    async def _tier_cloudscraper(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        if not _has_cloudscraper:
            return None
        try:
            import asyncio

            import cloudscraper

            def _do_fetch() -> str | None:
                # cloudscraper's API is synchronous/blocking (create_scraper +
                # get). It runs inside asyncio.to_thread so it does not block
                # the event loop — same pattern as _tier_undetected.
                scraper = cloudscraper.create_scraper(
                    browser={"browser": "chrome", "platform": "windows", "mobile": False}
                )
                resp = scraper.get(url, timeout=30, headers={"User-Agent": self._rotate_ua()})
                if resp.status_code == 200:
                    return resp.text
                return None

            return await asyncio.to_thread(_do_fetch)
        except Exception as e:
            logger.debug("cloudscraper_failed", extra={"error": str(e)[:50]})
        return None

    async def _tier_flaresolverr(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        from pry.core.settings import settings

        if not settings.flaresolverr_url:
            return None
        try:
            payload = {"cmd": "request.get", "url": url, "maxTimeout": 60000}
            c = await _get_shared_client()
            r = await c.post(settings.flaresolverr_url, json=payload, timeout=60)
            if r.is_success:
                data = r.json()
                solution = data.get("solution", {})
                if solution.get("status") == 200:
                    return solution["response"]
        except (httpx.HTTPError, httpx.RequestError) as e:
            logger.debug("flaresolverr_failed", extra={"error": str(e)[:50]})
        return None

    async def _tier_undetected(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        if not _has_undetected:
            return None
        try:
            import asyncio
            import time

            def _do_fetch() -> str:
                # Reuse the pooled driver (launched once) instead of launching
                # a fresh Chrome per request. The pool serializes access with a
                # lock because a single driver can only navigate one page at a
                # time.
                driver = get_browser_pool().get_uc_driver()
                try:
                    driver.get(url)
                    # Note: time.sleep is used inside a sync thread-pool task because
                    # undetected_chromedriver's blocking API runs in asyncio.to_thread.
                    # Replacing with asyncio.sleep would require restructuring the tier
                    # to be fully async; this sync sleep is bounded and does not block
                    # the event loop directly.
                    time.sleep(_RNG.uniform(2, 4))
                    return driver.page_source
                finally:
                    # The driver is pooled and must NOT be quit here — quitting
                    # would discard the cached Chrome process. Only the page is
                    # reset for the next request.
                    try:
                        driver.get("about:blank")
                    except Exception:
                        logger.debug("undetected_reset_failed", exc_info=True)

            return await asyncio.to_thread(_do_fetch)
        except Exception as e:
            logger.debug("undetected_failed", extra={"error": str(e)[:50]})
        return None

    async def _tier_playwright(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        if not _has_playwright:
            return None
        try:
            # Reuse the pooled browser (launched once) instead of launching a
            # fresh Chromium per request. Each request gets an isolated context
            # that is closed after use — the browser itself stays alive.
            browser = await get_browser_pool().get_playwright_browser()
            context = await browser.new_context(
                viewport={
                    "width": _RNG.choice([1920, 1366, 1440]),
                    "height": _RNG.choice([1080, 768, 900]),
                },
                user_agent=self._rotate_ua(),
                locale="en-US",
                timezone_id="America/New_York",
            )
            try:
                stealth_script = _stealth_engine.generate_all() if _stealth_engine else ""
                if stealth_script:
                    await context.add_init_script(stealth_script)
                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(_RNG.randint(1000, 3000))
                for _ in range(_RNG.randint(2, 5)):
                    await page.evaluate(f"window.scrollBy(0, {_RNG.randint(200, 500)})")
                    await page.wait_for_timeout(_RNG.randint(300, 1000))
                    await page.mouse.move(_RNG.randint(100, 1400), _RNG.randint(100, 800))
                return await page.content()
            finally:
                # Always close the context — a page-goto timeout (up to 60s)
                # or any other failure would otherwise leak a context per
                # failed attempt. The pooled browser is NOT closed here.
                try:
                    await context.close()
                except Exception:
                    logger.debug("playwright_context_close_failed", exc_info=True)
        except OSError as e:
            logger.debug("playwright_failed", extra={"error": str(e)[:50]})
        return None

    async def _tier_tls_fingerprint(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        """Fetch using curl_cffi TLS fingerprint impersonation."""
        if not self._tls_scraper or not self._tls_scraper.is_available():
            return None
        try:
            result = await self._tls_scraper.fetch(
                url,
                headers=self._build_headers(url),
                proxy=proxy_url or "",
                timeout_s=opts.get("timeout", 30),
            )
            if result.get("success") and result.get("status_code", 0) < 400:
                return result.get("text", "")
        except Exception as e:
            logger.debug("tls_fingerprint_failed", extra={"error": str(e)[:50]})
        return None

    async def _tier_camoufox(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        """Fetch using Camoufox anti-detection Firefox."""
        if not self._camoufox or not self._camoufox.is_available():
            return None
        try:
            result = await self._camoufox.fetch(
                url,
                wait_time=opts.get("wait_time", 3000),
                proxy=proxy_url or "",
            )
            if result.get("success"):
                return result.get("content", "")
        except Exception as e:
            logger.debug("camoufox_failed", extra={"error": str(e)[:50]})
        return None

    async def _tier_googlebot(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        try:
            headers = self._build_headers(url)
            headers["User-Agent"] = (
                "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
            )
            # Proxy is client-level httpx config; only a dedicated client is
            # needed when a proxy is set. The no-proxy path reuses the shared
            # pooled client (get_client).
            if proxy_url:
                async with httpx.AsyncClient(timeout=30, proxy=proxy_url) as c:
                    r = await safe_get(c, url, headers=headers)
            else:
                c = await _get_shared_client()
                r = await safe_get(c, url, headers=headers, timeout=30)
            if r.is_success:
                return r.text
        except (httpx.HTTPError, httpx.RequestError) as e:
            logger.debug("googlebot_failed", extra={"error": str(e)[:50]})
        return None

    async def _tier_archive(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        """Fetch from Wayback Machine CDX API for latest snapshot."""
        try:
            # URL-encode the target before embedding it in the CDX query param
            # and the archive path. An unencoded query string (e.g. ?a=1&b=2)
            # would corrupt the surrounding URL (the & becomes a param separator
            # in the CDX call and breaks the /web/{ts}id_/ path entirely).
            target = quote(url, safe="")
            cdx_url = f"https://web.archive.org/cdx/search/cdx?url={target}&output=json&limit=1&fl=timestamp,original"
            c = await _get_shared_client()
            r = await c.get(cdx_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            if r.is_success:
                data = r.json()
                if len(data) > 1:
                    timestamp = data[1][0]
                    archive_url = f"https://web.archive.org/web/{timestamp}id_/{target}"
                    ar = await safe_get(c, archive_url, timeout=30)
                    if ar.is_success:
                        return ar.text
        except (httpx.HTTPError, httpx.RequestError) as e:
            logger.debug("archive_failed", extra={"error": str(e)[:50]})
        return None

    async def _tier_google_cache(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        try:
            # Same encoding requirement as the archive tier: an unencoded
            # query string would be parsed as extra params of the cache URL.
            target = quote(url, safe="")
            cache_url = f"https://webcache.googleusercontent.com/search?q=cache:{target}"
            c = await _get_shared_client()
            r = await safe_get(c, cache_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            if r.is_success:
                return r.text
        except (httpx.HTTPError, httpx.RequestError) as e:
            logger.debug("google_cache_failed", extra={"error": str(e)[:50]})
        return None

    async def _tier_tor(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        """Fetch via Tor SOCKS5 proxy."""
        if not _has_tor:
            return None
        aiohttp: Any = None
        ProxyConnector: Any = None  # noqa: N806 - class binding mirrors import
        try:
            import aiohttp
            from aiohttp_socks import ProxyConnector

            connector = ProxyConnector.from_url("socks5://127.0.0.1:9050")
            async with (
                aiohttp.ClientSession(connector=connector) as session,
                session.get(
                    url,
                    headers=self._build_headers(url),
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp,
            ):
                if resp.status == 200:
                    return await resp.text()
        except aiohttp.ClientError as e:
            logger.debug("tor_failed", extra={"error": str(e)[:50]})
        return None

    async def _tier_ai_visual(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        """Tier 13: AI Visual Scraper — screenshot + LLM vision extraction."""
        if not _has_ai_visual or not _ai_visual:
            return None
        try:
            return await _ai_visual.scrape(url, opts)
        except Exception as e:
            logger.debug("ai_visual_failed", extra={"error": str(e)[:50]})
        return None

    async def _tier_mobile_app(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        """Tier 14: Mobile App API — impersonate mobile clients."""
        if not _has_mobile or not _mobile_scraper:
            return None
        try:
            return await _mobile_scraper.scrape(url, opts)
        except Exception as e:
            logger.debug("mobile_app_failed", extra={"error": str(e)[:50]})
        return None

    async def _tier_graphql(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        """Tier 15: GraphQL API Discovery — find and query GraphQL endpoints."""
        if not _has_graphql or not _graphql_scraper:
            return None
        try:
            return await _graphql_scraper.scrape(url, opts)
        except Exception as e:
            logger.debug("graphql_failed", extra={"error": str(e)[:50]})
        return None
