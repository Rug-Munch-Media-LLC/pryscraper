"""Pry — Anti-detection web scraper engine.
4-tier extraction with browser fingerprint spoofing, rotating headers,
Cloudflare bypass, CAPTCHA detection, and adaptive retry.
Beats every anti-bot system: Cloudflare, DataDome, Akamai, PerimeterX."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import asyncio
import random
import re
from typing import Any, ClassVar
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura
from trafilatura.settings import use_config

from settings import settings

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
]

CLOUDFLARE_INDICATORS = [
    "cf-browser-verification",
    "cf-challenge",
    "cloudflare",
    "awsWafCookieDomainList",
    "challenge-platform",
    "data-cf-script",
    "checking your browser",
    "ddos protection",
    "just a moment",
    "security check",
    "enable javascript",
    "verify you are human",
    "_cf_chl_opt",
    "cf-ray",
    "cdn-cgi/challenge-platform",
]


class BlockDetector:
    """Detect anti-bot blocks by analyzing HTML, status codes, and headers."""

    VENDOR_PATTERNS: ClassVar[dict[str, list[str]]] = {
        "cloudflare": [
            "cloudflare",
            "cf-",
            "checking your browser",
            "attention required",
            "just a moment",
            "_cf_chl_opt",
            "cdn-cgi",
        ],
        "datadome": ["datadome", "blocked because we believe"],
        "akamai": ["akamai", "akamaiedge"],
        "imperva": ["imperva", "incapsula"],
    }

    GENERIC_PATTERNS: ClassVar[list[str]] = [
        "captcha",
        "access denied",
        "blocked",
        "too many requests",
        "rate limit",
        "403 forbidden",
        "503 service unavailable",
    ]

    def __init__(self, min_content_length: int = 500):
        self.min_content_length = min_content_length

    def detect(
        self, html: str, status_code: int, headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "blocked": False,
            "tier": None,
            "vendor": None,
            "confidence": 0.0,
            "reason": "",
        }
        headers = headers or {}
        lower_html = html.lower()
        server = headers.get("server", "").lower()
        cf_ray = headers.get("cf-ray", "")

        for vendor, patterns in self.VENDOR_PATTERNS.items():
            if any(re.search(p, lower_html) or re.search(p, server) for p in patterns):
                result.update(
                    {
                        "blocked": True,
                        "tier": "vendor",
                        "vendor": vendor,
                        "confidence": 0.95,
                        "reason": f"{vendor} block detected",
                    }
                )
                return result

        if status_code in (403, 503):
            result.update(
                {
                    "blocked": True,
                    "tier": "generic",
                    "vendor": "unknown",
                    "confidence": 0.8,
                    "reason": f"HTTP {status_code}",
                }
            )
            return result
        if status_code == 429:
            result.update(
                {
                    "blocked": True,
                    "tier": "generic",
                    "vendor": "rate_limit",
                    "confidence": 0.9,
                    "reason": "Rate limited",
                }
            )
            return result

        if any(re.search(p, lower_html) for p in self.GENERIC_PATTERNS):
            result.update(
                {
                    "blocked": True,
                    "tier": "generic",
                    "vendor": "unknown",
                    "confidence": 0.7,
                    "reason": "Block pattern matched",
                }
            )
            return result

        body = re.search(r"<body[^>]*>(.*?)</body>", html, re.DOTALL)
        body_text = re.sub(r"<[^>]+>", "", body.group(1) if body else "").strip()
        if body_text and len(body_text) < self.min_content_length:
            result.update(
                {
                    "blocked": True,
                    "tier": "structural",
                    "vendor": "empty_page",
                    "confidence": 0.4,
                    "reason": f"Body too short ({len(body_text)} chars)",
                }
            )

        if cf_ray and status_code >= 400:
            result.update(
                {
                    "blocked": True,
                    "tier": "vendor",
                    "vendor": "cloudflare",
                    "confidence": 0.85,
                    "reason": "Cloudflare challenge",
                }
            )
            return result

        return result


class PryScraper:
    """Unified 10-tier anti-detection scraper with automatic fallback.
    Tier 1-10: direct → cloudscraper → flaresolverr → undetected → playwright → googlebot → tor → archive.org → google cache → textise
    """

    def __init__(self):
        self.config = use_config()
        self.config.set("DEFAULT", "extraction_corkboard", "false")
        self.config.set("DEFAULT", "max_file_size", "5000000")
        self.flare_available = True
        self.playwright_available = False
        self._check_playwright()
        self._ultimate = None
        self._ua_index = 0

    def _check_playwright(self):
        import os
        import shutil

        try:
            self.playwright_available = (
                shutil.which("chromium") is not None
                or shutil.which("chromium-browser") is not None
                or shutil.which("google-chrome") is not None
                or shutil.which("google-chrome-stable") is not None
            )
            # Check Playwright's managed browser cache
            if not self.playwright_available:
                home = os.path.expanduser("~")
                pw_cache = os.path.join(home, ".cache", "ms-playwright")
                if os.path.isdir(pw_cache):
                    for entry in os.listdir(pw_cache):
                        if entry.startswith("chromium"):
                            browser_dir = os.path.join(pw_cache, entry)
                            chrome_bin = os.path.join(browser_dir, "chrome-linux64", "chrome")
                            chrome_bin2 = os.path.join(browser_dir, "chrome", "chrome")
                            if os.path.isfile(chrome_bin) or os.path.isfile(chrome_bin2):
                                self.playwright_available = True
                                break
                # Also check PIP playwright installs
                if not self.playwright_available:
                    try:
                        import subprocess

                        r = subprocess.run(
                            ["python3", "-m", "playwright", "install", "--dry-run", "chromium"],
                            capture_output=True,
                            text=True,
                            timeout=10,
                        )
                        if "chromium" in r.stdout:
                            self.playwright_available = True
                    except (subprocess.SubprocessError, OSError):
                        pass
        except (subprocess.SubprocessError, OSError):
            self.playwright_available = False

    def _rotate_ua(self) -> str:
        ua = USER_AGENTS[self._ua_index % len(USER_AGENTS)]
        self._ua_index += 1
        return ua

    def _build_headers(self, url: str) -> dict:
        parsed = urlparse(url)
        return {
            "User-Agent": self._rotate_ua(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": random.choice(
                ["en-US,en;q=0.9", "en-GB,en;q=0.8", "en-US,en;q=0.7,fr;q=0.3"]
            ),
            "Referer": f"https://{parsed.netloc}/",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "DNT": "1",
            "Connection": "keep-alive",
            "Cache-Control": "max-age=0",
        }

    def _is_cloudflare(self, html: str) -> bool:
        html_lower = html.lower()[:5000]
        for indicator in CLOUDFLARE_INDICATORS:
            if indicator.lower() in html_lower:
                return True
        # Check for very short / challenge-looking pages
        return bool(
            len(html) < 2000
            and "document" in html_lower
            and ("var " in html_lower or "function" in html_lower)
        )

    def _quality_score(self, content: str) -> int:
        """Score content quality 0-100. Low score triggers retry with better tier."""
        if not content or len(content) < 100:
            return 0
        score = 0
        score += min(len(content) / 500, 40)  # Length: up to 40 pts
        score += min(content.count(" ") / 50, 20)  # Word count: up to 20 pts
        score += min(len(re.findall(r"[.!?]", content)), 15)  # Sentences: up to 15 pts
        score += 10 if re.search(r"<p|<article|<main", content, re.I) else 0  # HTML structure
        score += 10 if re.search(r"[a-zA-Z]{4,}", content) else 0  # Real words
        score += 5 if re.search(r"\d{4}", content) else 0  # Has numbers (dates, prices)
        return min(int(score), 100)

    async def scrape(self, url: str, options: dict | None = None) -> dict[str, Any]:
        if not url or not url.startswith(("http://", "https://")):
            return {"status": "error", "url": url, "error": "Invalid URL", "content": ""}

        opts = options or {}

        # Use UltimateScraper for the 10-tier fetching
        if self._ultimate is None:
            from ultimate_scraper import UltimateScraper

            self._ultimate = UltimateScraper()

        result = await self._ultimate.scrape(url, opts)
        if result.get("status") != "ok":
            return result

        # Extract via trafilatura for structured markdown
        raw_html = result.get("raw_html", "")
        extracted = self._extract(raw_html, url, opts)

        quality = self._quality_score(extracted.get("content", ""))
        extracted["quality_score"] = quality
        extracted["method"] = result.get("method", "unknown")

        # Keep raw_html for template engines
        if "raw_html" not in extracted:
            extracted["raw_html"] = raw_html

        return extracted

    async def _scrape_attempt(self, url: str, opts: dict, attempt: int) -> dict:
        """Single scrape attempt with adaptive tier selection."""
        errors = []

        # Tier 1: Direct fetch (attempt 0, or if not previously blocked)
        if attempt == 0 and not opts.get("force_flaresolverr"):
            try:
                headers = self._build_headers(url)
                raw_html = await self._fetch_direct(url, headers, opts.get("timeout", 30))
                if self._is_cloudflare(raw_html):
                    errors.append("direct: Cloudflare detected")
                else:
                    result = self._extract(raw_html, url, opts)
                    if result.get("content") and len(result["content"]) > 100:
                        result["method"] = "direct"
                        return result
                    errors.append(f"direct: thin content ({len(result.get('content', ''))} chars)")
            except Exception as e:  # noqa: BLE001
                errors.append(f"direct: {str(e)[:80]}")

        # Tier 2: FlareSolverr (bypass Cloudflare/WAF)
        if self.flare_available:
            try:
                raw_html = await self._fetch_via_flaresolverr(
                    url, opts.get("timeout", 60) + attempt * 15
                )
                if self._is_cloudflare(raw_html):
                    errors.append("flaresolverr: still blocked")
                else:
                    result = self._extract(raw_html, url, {**opts, "_bypass_tried": True})
                    if result.get("content") and len(result["content"]) > 100:
                        result["method"] = "flaresolverr"
                        return result
                    errors.append(
                        f"flaresolverr: thin content ({len(result.get('content', ''))} chars)"
                    )
            except Exception as e:  # noqa: BLE001
                errors.append(f"flaresolverr: {str(e)[:80]}")

        # Tier 3: Playwright stealth (full browser with fingerprint)
        if self.playwright_available or opts.get("js_render"):
            try:
                raw_html = await self._fetch_via_playwright(
                    url, opts.get("timeout", 90) + attempt * 20
                )
                result = self._extract(raw_html, url, {**opts, "_bypass_tried": True})
                if result.get("content") and len(result["content"]) > 100:
                    result["method"] = "playwright"
                    return result
                errors.append("playwright: thin content")
            except Exception as e:  # noqa: BLE001
                errors.append(f"playwright: {str(e)[:80]}")

        # Tier 4: Raw retry with different UA + longer timeout
        try:
            raw_headers = self._build_headers(url)
            raw_headers["User-Agent"] = (
                "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
            )
            raw_html = await self._fetch_direct(url, raw_headers, opts.get("timeout", 30) + 15)
            result = self._extract(raw_html, url, opts)
            if result.get("content") and len(result["content"]) > 100:
                result["method"] = "googlebot"
                return result
            errors.append("googlebot: thin content")
        except Exception as e:  # noqa: BLE001
            errors.append(f"googlebot: {str(e)[:80]}")

        return {"status": "error", "url": url, "error": "; ".join(errors), "content": ""}

    def _extract(self, raw_html: str, url: str, opts: dict) -> dict:
        result = {"url": url, "status": "ok", "raw_html": raw_html}

        # Title extraction
        m = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.I | re.S)
        if m:
            result["title"] = m.group(1).strip()[:500]
        m = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', raw_html, re.I)
        if m:
            result["description"] = m.group(1).strip()[:500]

        # Primary: trafilatura
        content = trafilatura.extract(
            raw_html,
            config=self.config,
            include_links=opts.get("include_links", True),
            include_images=opts.get("include_images", False),
            include_formatting=opts.get("include_formatting", True),
            output_format="markdown",
            favor_precision=opts.get("favor_precision", False),
            favor_recall=opts.get("favor_recall", True),
        )
        if content:
            result["content"] = content
            return result

        # Fallback: markdownify
        from markdownify import markdownify

        content = markdownify(raw_html, heading_arrows=False, strip=["script", "style"])
        content = re.sub(r"\n{3,}", "\n\n", content)[:100000]
        result["content"] = content
        return result

    async def _fetch_direct(self, url: str, headers: dict, timeout: int) -> str:
        proxy_url = settings.resolved_proxy_url
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=20),
            headers=headers,
            cookies=httpx.Cookies(),
            proxy=proxy_url,
        ) as client:
            delay = random.uniform(*settings.rotation_delay_range)
            await asyncio.sleep(delay)
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text

    async def _fetch_via_flaresolverr(self, url: str, timeout: int) -> str:
        payload = {"cmd": "request.get", "url": url, "maxTimeout": timeout * 1000}
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout + 10)) as client:
            resp = await client.post(settings.flaresolverr_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            solution = data.get("solution", {})
            if solution.get("status") == 200:
                return solution["response"]
            raise Exception(
                f"FlareSolverr status {solution.get('status')}: {solution.get('status', '')[:200]}"
            )

    async def _fetch_via_playwright(self, url: str, timeout: int) -> str:
        """Full browser rendering with human-like behavior and stealth fingerprint."""
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-web-security",
                    "--disable-features=IsolateOrigins,site-per-process",
                ],
            )
            context = await browser.new_context(
                viewport={
                    "width": random.choice([1920, 1366, 1440]),
                    "height": random.choice([1080, 768, 900]),
                },
                user_agent=self._rotate_ua(),
                locale=random.choice(["en-US", "en-GB", "en-CA"]),
                timezone_id=random.choice(["America/New_York", "Europe/London", "America/Chicago"]),
                permissions=["geolocation"],
                geolocation={"latitude": 40.7128, "longitude": -74.0060},
            )
            # Stealth: override automation indicators
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                window.chrome = { runtime: {} };
                // Override permissions query to avoid automation detection
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (p) => (
                    p.name === 'notifications' ? Promise.resolve({state: 'denied'}) : originalQuery(p)
                );
            """)
            page = await context.new_page()
            # Human-like navigation: random wait before page load
            await asyncio.sleep(random.uniform(0.5, 2.0))
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            # Wait for page to settle (random human delay)
            await page.wait_for_timeout(random.randint(1000, 3000))
            # Human-like scrolling: step scroll with random pauses
            scroll_height = await page.evaluate("document.body.scrollHeight")
            steps = random.randint(3, 7)
            for step in range(steps):
                target = (scroll_height * (step + 1)) / steps
                await page.evaluate(f"window.scrollTo({{ top: {target}, behavior: 'smooth' }})")
                await page.wait_for_timeout(random.randint(300, 1200))
                # Random mouse movement
                await page.mouse.move(
                    random.randint(100, 1800),
                    random.randint(100, 900),
                    steps=random.randint(3, 8),
                )
            # Scroll back up like a human reading
            await page.evaluate("window.scrollTo({ top: 0, behavior: 'smooth' })")
            await page.wait_for_timeout(random.randint(500, 1500))
            content = await page.content()
            await browser.close()
            return content

    async def crawl(self, url: str, options: dict | None = None) -> list[dict]:
        opts = options or {}
        max_pages = opts.get("max_pages", 10)
        max_depth = opts.get("max_depth", 2)
        visited, to_visit, results = set(), [(url, 0)], []

        while to_visit and len(visited) < max_pages:
            current_url, depth = to_visit.pop(0)
            if current_url in visited or depth > max_depth:
                continue
            visited.add(current_url)
            try:
                result = await self.scrape(current_url, opts)
                if result.get("status") == "ok":
                    results.append(
                        {
                            "url": current_url,
                            "markdown": result.get("content", ""),
                            "title": result.get("title", ""),
                            "method": result.get("method", "unknown"),
                        }
                    )
                if depth < max_depth:
                    links = await self._extract_links(
                        current_url, {"limit": max_pages - len(visited)}
                    )
                    to_visit.extend((link, depth + 1) for link in links if link not in visited)
            except Exception:  # noqa: BLE001
                continue
        return results

    async def map_urls(self, url: str, options: dict | None = None) -> list[str]:
        try:
            return await self._extract_links(url, options or {})
        except Exception:  # noqa: BLE001
            return []

    async def _extract_links(self, url: str, options: dict | None = None) -> list[str]:
        opts = options or {}
        base_domain = urlparse(url).netloc
        html = None
        try:
            html = await self._fetch_direct(url, self._build_headers(url), 15)
        except Exception:  # noqa: BLE001
            try:
                html = await self._fetch_via_flaresolverr(url, 30)
            except Exception:  # noqa: BLE001
                return []
        links = set()
        for m in re.finditer(r'href=["\'](https?://[^"\']+)["\']', html):
            link = m.group(1)
            if urlparse(link).netloc == base_domain:
                links.add(link.split("#")[0].rstrip("/"))
        for m in re.finditer(r'href=["\'](/[^"\']+)["\']', html):
            link = urljoin(url, m.group(1))
            if urlparse(link).netloc == base_domain:
                links.add(link.split("#")[0].rstrip("/"))
        return sorted(links)[: opts.get("limit", 50)]
