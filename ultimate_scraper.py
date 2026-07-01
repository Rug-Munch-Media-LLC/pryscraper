"""Pry — Ultimate Anti-Detection Scraper.
Multi-strategy scraping with 10+ bypass methods and intelligent fallback.
Beats Cloudflare, DataDome, Akamai, Imperva, PerimeterX, and generic blocks."""

import logging
import os
import random
import re
from typing import Any, ClassVar
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Try importing optional bypass libraries
_has_cloudscraper = False
_has_undetected = False
_has_playwright = False

try:
    import cloudscraper

    _has_cloudscraper = True
except ImportError:
    pass

try:
    import undetected_chromedriver as uc

    _has_undetected = True
except ImportError:
    pass

try:
    from playwright.async_api import async_playwright

    _has_playwright = True
except ImportError:
    pass

try:
    from aiohttp_socks import ProxyConnector

    _has_tor = True
except ImportError:
    _has_tor = False


class UltimateScraper:
    """10-tier anti-detection scraper with automatic fallback.

    Tiers:
    1. Direct HTTP (smart headers, rotating UAs)
    2. cloudscraper (Python-native Cloudflare bypass)
    3. FlareSolverr (Cloudflare/WAF bypass service)
    4. undetected-chromedriver (modified Chrome, no detection)
    5. Playwright stealth (full browser with human behavior)
    6. Googlebot UA (search engine crawl mimic)
    7. Tor proxy (anonymous routing via SOCKS5)
    8. Archive.org / Wayback Machine (cached version)
    9. Google Cache (cached version)
    10. Textise dot iitty (text-only version)
    """

    USER_AGENTS: ClassVar[list[str]] = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    ]

    def __init__(self) -> None:
        self._ua_index = 0

    def _rotate_ua(self) -> str:
        ua = self.USER_AGENTS[self._ua_index % len(self.USER_AGENTS)]
        self._ua_index += 1
        return ua

    def _build_headers(self, url: str) -> dict[str, str]:
        parsed = urlparse(url)
        return {
            "User-Agent": self._rotate_ua(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": random.choice(
                ["en-US,en;q=0.9", "en-GB,en;q=0.8", "en-US,en;q=0.7"]
            ),
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

        proxy_url = self._resolve_proxy_url(opts)

        # Tier 0: Premium proxy (if configured and forced or first attempt)
        if proxy_url and opts.get("use_premium_proxy_first", True):
            html = await self._tier_premium_proxy(url, proxy_url, opts)
            if html and self._is_valid(html):
                return self._result(url, html, "premium_proxy")
            errors.append("premium_proxy_failed")

        # Tier 1: Direct HTTP
        html = await self._tier_direct(url, opts, proxy_url=proxy_url)
        if html and self._is_valid(html):
            return self._result(url, html, "direct")

        # Tier 2: cloudscraper (Python Cloudflare bypass)
        html = await self._tier_cloudscraper(url, opts)
        if html and self._is_valid(html):
            return self._result(url, html, "cloudscraper")

        # Tier 3: FlareSolverr
        html = await self._tier_flaresolverr(url, opts)
        if html and self._is_valid(html):
            return self._result(url, html, "flaresolverr")

        # Tier 4: undetected-chromedriver
        html = await self._tier_undetected(url, opts)
        if html and self._is_valid(html):
            return self._result(url, html, "undetected")

        # Tier 5: Playwright stealth
        html = await self._tier_playwright(url, opts)
        if html and self._is_valid(html):
            return self._result(url, html, "playwright")

        # Tier 6: Googlebot UA
        html = await self._tier_googlebot(url, opts, proxy_url=proxy_url)
        if html and self._is_valid(html):
            return self._result(url, html, "googlebot")

        # Tier 7: Premium proxy retry (after cheap tiers fail)
        if proxy_url and not opts.get("use_premium_proxy_first", True):
            html = await self._tier_premium_proxy(url, proxy_url, opts)
            if html and self._is_valid(html):
                return self._result(url, html, "premium_proxy")
            errors.append("premium_proxy_failed")

        # Tier 8: Archive.org / Wayback Machine
        html = await self._tier_archive(url, opts)
        if html and self._is_valid(html):
            return self._result(url, html, "archive")

        # Tier 9: Google Cache
        html = await self._tier_google_cache(url, opts)
        if html and self._is_valid(html):
            return self._result(url, html, "google_cache")

        # Tier 10: Tor (anonymous routing)
        html = await self._tier_tor(url, opts)
        if html and self._is_valid(html):
            return self._result(url, html, "tor")

        last_err = errors[-1] if errors else "all_tiers_failed"
        return {
            "status": "error",
            "url": url,
            "error": "; ".join(errors[-5:]) if errors else last_err,
            "content": "",
            "proxy_recommendation": self._recommend_proxy(last_err),
        }

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
        except Exception as e:
            logger.debug("proxy_resolve_failed", extra={"error": str(e)[:80]})
        env_url = os.getenv("PRY_PROXY_URL") or os.getenv("PROXY_URL")
        return env_url or None

    def _recommend_proxy(self, last_error: str) -> dict[str, Any] | None:
        """Build a proxy recommendation for the response when scraping fails."""
        try:
            from proxy_manager import ProxyManager

            return ProxyManager().get_recommendation(last_error)
        except Exception as e:
            logger.debug("proxy_recommend_failed", extra={"error": str(e)[:80]})
            return None

    def _result(self, url: str, html: str, method: str) -> dict[str, Any]:
        return {
            "status": "ok",
            "url": url,
            "raw_html": html,
            "method": method,
            "content": self._extract_text(html),
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
        except Exception:
            pass
        try:
            from readability import Document

            doc = Document(html)
            content = doc.summary()
            if content and len(content) > 100:
                from markdownify import markdownify

                return markdownify(content, heading_arrows=False, strip=["script", "style"])
        except Exception:
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

            async with httpx.AsyncClient(
                timeout=30, follow_redirects=True, proxy=proxy_url
            ) as c:
                r = await c.get(url, headers=self._build_headers(url))
                if r.is_success:
                    return r.text
        except Exception as e:
            logger.debug("direct_failed", extra={"error": str(e)[:50]})
        return None

    async def _tier_premium_proxy(
        self, url: str, proxy_url: str, opts: dict[str, Any]
    ) -> str | None:
        """Fetch via the configured premium residential/datacenter proxy."""
        try:
            import httpx

            async with httpx.AsyncClient(
                timeout=45, follow_redirects=True, proxy=proxy_url
            ) as c:
                r = await c.get(url, headers=self._build_headers(url))
                if r.is_success:
                    return r.text
        except Exception as e:
            logger.debug("premium_proxy_failed", extra={"error": str(e)[:50]})
        return None

    async def _tier_cloudscraper(self, url: str, opts: dict[str, Any]) -> str | None:
        if not _has_cloudscraper:
            return None
        try:
            scraper = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "windows", "mobile": False}
            )
            resp = scraper.get(url, timeout=30, headers={"User-Agent": self._rotate_ua()})
            if resp.status_code == 200:
                return resp.text
        except Exception as e:
            logger.debug("cloudscraper_failed", extra={"error": str(e)[:50]})
        return None

    async def _tier_flaresolverr(self, url: str, opts: dict[str, Any]) -> str | None:
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
        except Exception as e:
            logger.debug("flaresolverr_failed", extra={"error": str(e)[:50]})
        return None

    async def _tier_undetected(self, url: str, opts: dict[str, Any]) -> str | None:
        if not _has_undetected:
            return None
        try:
            import asyncio
            import time

            def _do_fetch() -> str:
                import undetected_chromedriver as uc

                driver = uc.Chrome(headless=True, use_subprocess=True)
                driver.get(url)
                time.sleep(random.uniform(2, 4))
                html = driver.page_source
                driver.quit()
                return html

            return await asyncio.to_thread(_do_fetch)
        except Exception as e:
            logger.debug("undetected_failed", extra={"error": str(e)[:50]})
        return None

    async def _tier_playwright(self, url: str, opts: dict[str, Any]) -> str | None:
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
                context = await browser.new_context(
                    viewport={
                        "width": random.choice([1920, 1366, 1440]),
                        "height": random.choice([1080, 768, 900]),
                    },
                    user_agent=self._rotate_ua(),
                    locale="en-US",
                    timezone_id="America/New_York",
                )
                await context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    navigator.permissions.query = (p) => p.name === 'notifications' ? Promise.resolve({state: 'denied'}) : navigator.permissions.query(p);
                """)
                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(random.randint(1000, 3000))
                for _ in range(random.randint(2, 5)):
                    await page.evaluate(f"window.scrollBy(0, {random.randint(200, 500)})")
                    await page.wait_for_timeout(random.randint(300, 1000))
                    await page.mouse.move(random.randint(100, 1400), random.randint(100, 800))
                html = await page.content()
                await browser.close()
                return html
        except Exception as e:
            logger.debug("playwright_failed", extra={"error": str(e)[:50]})
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
            async with httpx.AsyncClient(
                timeout=30, follow_redirects=True, proxy=proxy_url
            ) as c:
                r = await c.get(url, headers=headers)
                if r.is_success:
                    return r.text
        except Exception as e:
            logger.debug("googlebot_failed", extra={"error": str(e)[:50]})
        return None

    async def _tier_archive(self, url: str, opts: dict[str, Any]) -> str | None:
        """Fetch from Wayback Machine CDX API for latest snapshot."""
        try:
            import httpx

            cdx_url = f"https://web.archive.org/cdx/search/cdx?url={url}&output=json&limit=1&fl=timestamp,original"
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(cdx_url, headers={"User-Agent": "Mozilla/5.0"})
                if r.is_success:
                    data = r.json()
                    if len(data) > 1:
                        timestamp = data[1][0]
                        archive_url = f"https://web.archive.org/web/{timestamp}id_/{url}"
                        ar = await c.get(archive_url, timeout=30, follow_redirects=True)
                        if ar.is_success:
                            return ar.text
        except Exception as e:
            logger.debug("archive_failed", extra={"error": str(e)[:50]})
        return None

    async def _tier_google_cache(self, url: str, opts: dict[str, Any]) -> str | None:
        try:
            import httpx

            cache_url = f"https://webcache.googleusercontent.com/search?q=cache:{url}"
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
                r = await c.get(cache_url, headers={"User-Agent": "Mozilla/5.0"})
                if r.is_success:
                    return r.text
        except Exception as e:
            logger.debug("google_cache_failed", extra={"error": str(e)[:50]})
        return None

    async def _tier_tor(self, url: str, opts: dict[str, Any]) -> str | None:
        """Fetch via Tor SOCKS5 proxy."""
        if not _has_tor:
            return None
        try:
            import aiohttp
            from aiohttp_socks import ProxyConnector

            connector = ProxyConnector.from_url("socks5://127.0.0.1:9050")
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(
                    url,
                    headers=self._build_headers(url),
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status == 200:
                        return await resp.text()
        except Exception as e:
            logger.debug("tor_failed", extra={"error": str(e)[:50]})
        return None
