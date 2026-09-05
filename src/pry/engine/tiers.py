"""Tier implementations for the UltimateScraper fallback chain.

Holds the concrete ``_tier_*`` fetch strategies plus the shared helpers they
use (header building, content validation, text extraction, block-signal
detection, fallback telemetry). ``UltimateScraper`` composes these via
``TierMixin``; the fallback-chain orchestration stays in
``ultimate_scraper.py``.

Availability flags (``_has_cloudscraper`` etc.) remain module-level globals
on ``pry.engine.ultimate_scraper`` because tests patch them there; tier
methods resolve them lazily through :func:`_us_flag` so patches stay
effective.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import time
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from pry.engine.browser_pool import get_browser_pool
from pry.engine.url_guard import safe_get

_RNG = random.SystemRandom()

logger = logging.getLogger(__name__)


def _us_flag(name: str) -> Any:
    """Read an availability flag / scraper object from ultimate_scraper.

    Lazy module lookup (never at import time) avoids a circular import while
    keeping ``patch("pry.engine.ultimate_scraper._has_x", ...)`` effective.
    """
    from pry.engine import ultimate_scraper as _us

    return getattr(_us, name)


async def _get_shared_client() -> httpx.AsyncClient:
    """Lazy import to avoid engine→api boundary violation (import-linter)."""
    from pry.core.client import get_client

    return await get_client()


class TierMixin:
    """Concrete scraping tiers, mixed into :class:`UltimateScraper`."""

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
        if not _us_flag("_HAS_BLOCK_DETECTION"):
            return None
        block_detect = _us_flag("_block_detect")
        if html is not None:
            return block_detect(html, 200, {})
        return block_detect("", 0, {})

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
        if not _us_flag("_HAS_FALLBACK_TELEMETRY"):
            return
        try:
            _us_flag("_record_fallback")(
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
            logger.debug("direct_failed", extra={"error": str(e)[:200]})
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
            logger.debug("premium_proxy_failed", extra={"error": str(e)[:200]})
        return None

    async def _tier_cloudscraper(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        if not _us_flag("_has_cloudscraper"):
            return None
        try:
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
            logger.debug("cloudscraper_failed", extra={"error": str(e)[:200]})
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
            logger.debug("flaresolverr_failed", extra={"error": str(e)[:200]})
        return None

    async def _tier_undetected(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        if not _us_flag("_has_undetected"):
            return None
        try:
            import time as _time

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
                    _time.sleep(_RNG.uniform(2, 4))
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
            logger.debug("undetected_failed", extra={"error": str(e)[:200]})
        return None

    async def _tier_playwright(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        if not _us_flag("_has_playwright"):
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
                stealth_engine = _us_flag("_stealth_engine")
                stealth_script = stealth_engine.generate_all() if stealth_engine else ""
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
            logger.debug("playwright_failed", extra={"error": str(e)[:200]})
        return None

    async def _tier_tls_fingerprint(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        """Fetch using curl_cffi TLS fingerprint impersonation."""
        tls_scraper = getattr(self, "_tls_scraper", None)
        if not tls_scraper or not tls_scraper.is_available():
            return None
        try:
            result = await tls_scraper.fetch(
                url,
                headers=self._build_headers(url),
                proxy=proxy_url or "",
                timeout_s=opts.get("timeout", 30),
            )
            if result.get("success") and result.get("status_code", 0) < 400:
                return result.get("text", "")
        except Exception as e:
            logger.debug("tls_fingerprint_failed", extra={"error": str(e)[:200]})
        return None

    async def _tier_camoufox(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        """Fetch using Camoufox anti-detection Firefox."""
        camoufox = getattr(self, "_camoufox", None)
        if not camoufox or not camoufox.is_available():
            return None
        try:
            result = await camoufox.fetch(
                url,
                wait_time=opts.get("wait_time", 3000),
                proxy=proxy_url or "",
            )
            if result.get("success"):
                return result.get("content", "")
        except Exception as e:
            logger.debug("camoufox_failed", extra={"error": str(e)[:200]})
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
            logger.debug("googlebot_failed", extra={"error": str(e)[:200]})
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
            logger.debug("archive_failed", extra={"error": str(e)[:200]})
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
            logger.debug("google_cache_failed", extra={"error": str(e)[:200]})
        return None

    async def _tier_tor(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        """Fetch via Tor SOCKS5 proxy."""
        if not _us_flag("_has_tor"):
            return None
        aiohttp: Any = None
        ProxyConnector: Any = None  # noqa: N806 - class binding mirrors import
        try:
            import aiohttp
            from aiohttp_socks import ProxyConnector

            tor_host = os.getenv("TOR_SOCKS5_HOST", "127.0.0.1")
            tor_port = os.getenv("TOR_SOCKS5_PORT", "9050")
            connector = ProxyConnector.from_url(f"socks5://{tor_host}:{tor_port}")
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
            logger.debug("tor_failed", extra={"error": str(e)[:200]})
        return None

    async def _tier_ai_visual(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        """Tier 13: AI Visual Scraper — screenshot + LLM vision extraction."""
        if not _us_flag("_has_ai_visual") or not _us_flag("_ai_visual"):
            return None
        try:
            return await _us_flag("_ai_visual").scrape(url, opts)
        except Exception as e:
            logger.debug("ai_visual_failed", extra={"error": str(e)[:200]})
        return None

    async def _tier_mobile_app(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        """Tier 14: Mobile App API — impersonate mobile clients."""
        if not _us_flag("_has_mobile") or not _us_flag("_mobile_scraper"):
            return None
        try:
            return await _us_flag("_mobile_scraper").scrape(url, opts)
        except Exception as e:
            logger.debug("mobile_app_failed", extra={"error": str(e)[:200]})
        return None

    async def _tier_graphql(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        """Tier 15: GraphQL API Discovery — find and query GraphQL endpoints."""
        if not _us_flag("_has_graphql") or not _us_flag("_graphql_scraper"):
            return None
        try:
            return await _us_flag("_graphql_scraper").scrape(url, opts)
        except Exception as e:
            logger.debug("graphql_failed", extra={"error": str(e)[:200]})
        return None
