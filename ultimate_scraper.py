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
import time
from typing import Any, ClassVar
from urllib.parse import quote, urlparse

from errors import InvalidRequestError
from observability import SCRAPE_LATENCY
from resilience import registry
from retry import RetryConfig, async_retry
from url_guard import safe_get, validate_url

# SystemRandom: crypto-grade entropy so stealth jitter is not predictable.
_RNG = random.SystemRandom()

logger = logging.getLogger(__name__)

# Try importing optional bypass libraries
_has_cloudscraper = importlib.util.find_spec("cloudscraper") is not None
_has_undetected = importlib.util.find_spec("undetected_chromedriver") is not None
_has_playwright = importlib.util.find_spec("playwright") is not None
_has_tor = importlib.util.find_spec("aiohttp_socks") is not None

if _has_playwright:
    from playwright.async_api import async_playwright

try:
    from tls_fingerprint import TLSScraper

    _has_tls = True
except ImportError:
    _has_tls = False

try:
    from camoufox_integration import CamoufoxBrowser

    _has_camoufox = True
except ImportError:
    _has_camoufox = False

_stealth_engine: StealthEngine | None
try:
    from stealth_engine import StealthEngine

    _stealth_engine = StealthEngine()
except ImportError:
    _stealth_engine = None

# Optional block-detection + fallback-telemetry integration (guarded so the
# scraper still works if either module is unavailable at runtime).
_HAS_BLOCK_DETECTION = False
_block_detect: Any = None
try:
    from block_detection import detect_block as _block_detect

    _HAS_BLOCK_DETECTION = True
except ImportError:  # pragma: no cover - optional dependency
    pass

_HAS_FALLBACK_TELEMETRY = False
_record_fallback: Any = None
try:
    from fallback_telemetry import record_fallback

    _record_fallback = record_fallback
    _HAS_FALLBACK_TELEMETRY = True
except ImportError:  # pragma: no cover - optional dependency
    pass


class UltimateScraper:
    """12-tier anti-detection scraper with automatic fallback.

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

    The per-domain order is adaptive: resilience.DomainTierMemory promotes
    the domain's proven-best tier to the front and demotes/skips tiers that
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
        Will try up to 10 strategies until one succeeds."""
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
            except Exception as e:  # noqa: BLE001
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
            from proxy_manager import ProxyManager

            pm = ProxyManager()
            return pm.get_proxy_url()
        except Exception as e:  # noqa: BLE001
            logger.debug("proxy_resolve_failed", extra={"error": str(e)[:80]})
        env_url = os.getenv("PRY_PROXY_URL") or os.getenv("PROXY_URL")
        return env_url or None

    def _recommend_proxy(self, last_error: str) -> dict[str, Any] | None:
        """Build a proxy recommendation for the response when scraping fails."""
        try:
            from proxy_manager import ProxyManager

            return ProxyManager().get_recommendation(last_error)
        except Exception as e:  # noqa: BLE001
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
        except Exception:  # noqa: BLE001 - telemetry must never break scraping
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
        except Exception:  # noqa: BLE001, S110 - fallback: try the next extractor
            pass
        try:
            from readability import Document

            doc = Document(html)
            content = doc.summary()
            if content and len(content) > 100:
                from markdownify import markdownify

                return markdownify(content, heading_arrows=False, strip=["script", "style"])  # type: ignore[call-arg]  # markdownify supports heading_arrows at runtime
        except Exception:  # noqa: BLE001, S110 - fallback: strip tags as last resort
            pass
        # Last resort: strip HTML tags
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:50000] if len(text) > 50000 else text

    async def _tier_direct(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=30, proxy=proxy_url) as c:
                r = await safe_get(c, url, headers=self._build_headers(url))
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
            import httpx

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
            import cloudscraper

            scraper = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "windows", "mobile": False}
            )
            resp = scraper.get(url, timeout=30, headers={"User-Agent": self._rotate_ua()})
            if resp.status_code == 200:
                return resp.text
        except Exception as e:  # noqa: BLE001
            logger.debug("cloudscraper_failed", extra={"error": str(e)[:50]})
        return None

    async def _tier_flaresolverr(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        from settings import settings

        if not settings.flaresolverr_url:
            return None
        try:
            import httpx

            payload = {"cmd": "request.get", "url": url, "maxTimeout": 60000}
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(settings.flaresolverr_url, json=payload)
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
                import undetected_chromedriver as uc

                driver = None
                try:
                    driver = uc.Chrome(headless=True, use_subprocess=True)
                    driver.get(url)
                    # Note: time.sleep is used inside a sync thread-pool task because
                    # undetected_chromedriver's blocking API runs in asyncio.to_thread.
                    # Replacing with asyncio.sleep would require restructuring the tier
                    # to be fully async; this sync sleep is bounded and does not block
                    # the event loop directly.
                    time.sleep(_RNG.uniform(2, 4))
                    return driver.page_source
                finally:
                    # Always quit the driver — a page-goto timeout or any other
                    # exception would otherwise leak a Chrome process per failed
                    # attempt.
                    if driver is not None:
                        try:
                            driver.quit()
                        except Exception:  # noqa: BLE001 - cleanup must not mask the original error
                            logger.debug("undetected_quit_failed", exc_info=True)

            return await asyncio.to_thread(_do_fetch)
        except Exception as e:  # noqa: BLE001
            logger.debug("undetected_failed", extra={"error": str(e)[:50]})
        return None

    async def _tier_playwright(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        if not _has_playwright:
            return None
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-web-security",
                    ],
                )
                try:
                    context = await browser.new_context(
                        viewport={
                            "width": _RNG.choice([1920, 1366, 1440]),
                            "height": _RNG.choice([1080, 768, 900]),
                        },
                        user_agent=self._rotate_ua(),
                        locale="en-US",
                        timezone_id="America/New_York",
                    )
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
                    # Always close the browser — a page-goto timeout (up to 60s)
                    # or any other failure would otherwise leak a browser per
                    # failed attempt.
                    try:
                        await browser.close()
                    except Exception:  # noqa: BLE001 - cleanup must not mask the original error
                        logger.debug("playwright_close_failed", exc_info=True)
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
        except Exception as e:  # noqa: BLE001
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
        except Exception as e:  # noqa: BLE001
            logger.debug("camoufox_failed", extra={"error": str(e)[:50]})
        return None

    async def _tier_googlebot(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        try:
            import httpx

            headers = self._build_headers(url)
            headers["User-Agent"] = (
                "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
            )
            async with httpx.AsyncClient(timeout=30, proxy=proxy_url) as c:
                r = await safe_get(c, url, headers=headers)
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
            import httpx

            # URL-encode the target before embedding it in the CDX query param
            # and the archive path. An unencoded query string (e.g. ?a=1&b=2)
            # would corrupt the surrounding URL (the & becomes a param separator
            # in the CDX call and breaks the /web/{ts}id_/ path entirely).
            target = quote(url, safe="")
            cdx_url = f"https://web.archive.org/cdx/search/cdx?url={target}&output=json&limit=1&fl=timestamp,original"
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(cdx_url, headers={"User-Agent": "Mozilla/5.0"})
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
            import httpx

            # Same encoding requirement as the archive tier: an unencoded
            # query string would be parsed as extra params of the cache URL.
            target = quote(url, safe="")
            cache_url = f"https://webcache.googleusercontent.com/search?q=cache:{target}"
            async with httpx.AsyncClient(timeout=15) as c:
                r = await safe_get(c, cache_url, headers={"User-Agent": "Mozilla/5.0"})
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
