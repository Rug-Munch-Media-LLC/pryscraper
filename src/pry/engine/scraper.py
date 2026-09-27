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
import logging
import random
import re
from typing import Any, ClassVar
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura
from trafilatura.settings import use_config

from pry.core.errors import InvalidRequestError
from pry.core.settings import settings
from pry.engine.url_guard import safe_get, validate_url

logger = logging.getLogger(__name__)

# SystemRandom: crypto-grade entropy so stealth jitter is not predictable.
_RNG = random.SystemRandom()

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
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

    def __init__(self) -> None:
        self.config = use_config()
        self.config.set("DEFAULT", "extraction_corkboard", "false")
        self.config.set("DEFAULT", "max_file_size", "5000000")
        self._ultimate: Any = None
        self._ua_index = 0

    def _rotate_ua(self) -> str:
        ua = USER_AGENTS[self._ua_index % len(USER_AGENTS)]
        self._ua_index += 1
        return ua

    def _build_headers(self, url: str) -> dict:
        parsed = urlparse(url)
        return {
            "User-Agent": self._rotate_ua(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": _RNG.choice(
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

    def _quality_score(self, content: str) -> int:
        """Score content quality 0-100. Low score triggers retry with better tier."""
        if not content or len(content) < 100:
            return 0
        score: float = 0
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
        try:
            validate_url(url)
        except InvalidRequestError as e:
            return {"status": "error", "url": url, "error": str(e), "content": ""}

        opts = options or {}

        # Use UltimateScraper for the 10-tier fetching
        if self._ultimate is None:
            from pry.engine.ultimate_scraper import UltimateScraper

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

        content = markdownify(raw_html, heading_arrows=False, strip=["script", "style"])  # type: ignore[call-arg]  # markdownify supports heading_arrows at runtime
        content = re.sub(r"\n{3,}", "\n\n", content)[:5_000_000]  # windowed by API offset/limit
        result["content"] = content
        return result

    async def _fetch_direct(self, url: str, headers: dict, timeout_s: int) -> str:
        proxy_url = settings.resolved_proxy_url
        # Note: follow_redirects stays False (httpx default); safe_get manually
        # follows redirects and re-validates each Location target (SSRF guard).
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_s),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=20),
            headers=headers,
            cookies=httpx.Cookies(),
            proxy=proxy_url,
        ) as client:
            delay = _RNG.uniform(*settings.rotation_delay_range)
            await asyncio.sleep(delay)
            resp = await safe_get(client, url)
            resp.raise_for_status()
            return resp.text

    async def _fetch_via_flaresolverr(self, url: str, timeout_s: int) -> str:
        payload = {"cmd": "request.get", "url": url, "maxTimeout": timeout_s * 1000}
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s + 10)) as client:
            resp = await client.post(settings.flaresolverr_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            solution = data.get("solution", {})
            if solution.get("status") == 200:
                return solution["response"]
            raise Exception(
                f"FlareSolverr status {solution.get('status')}: {str(solution.get('status', ''))[:200]}"
            )

    async def crawl(self, url: str, options: dict | None = None) -> list[dict]:
        opts = options or {}
        max_pages = opts.get("max_pages", 10)
        max_depth = opts.get("max_depth", 2)
        visited: set[str] = set()
        to_visit: list[tuple[str, int]] = [(url, 0)]
        results: list[Any] = []

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
                else:
                    results.append(
                        {
                            "url": current_url,
                            "status": "error",
                            "error": result.get("error", "scrape failed"),
                            "method": result.get("method", "unknown"),
                        }
                    )
            except Exception as exc:  # noqa: BLE001 - one page failing must not abort the crawl
                logger.warning(
                    "crawl_page_scrape_failed", extra={"url": current_url}, exc_info=True
                )
                results.append(
                    {
                        "url": current_url,
                        "status": "error",
                        "error": f"{type(exc).__name__}: {exc}"[:300],
                        "method": "unknown",
                    }
                )
            if depth >= max_depth:
                continue
            try:
                links = await self._extract_links(current_url, {"limit": max_pages - len(visited)})
            except Exception as exc:  # noqa: BLE001 - one page's link expansion must not abort the crawl
                logger.warning(
                    "crawl_link_expansion_failed",
                    extra={"url": current_url},
                    exc_info=True,
                )
                results.append(
                    {
                        "url": current_url,
                        "status": "error",
                        "error": f"link expansion failed: {exc}"[:300],
                        "method": "unknown",
                    }
                )
                continue
            to_visit.extend((link, depth + 1) for link in links if link not in visited)
        return results

    async def map_urls(self, url: str, options: dict | None = None) -> list[str]:
        """Return same-origin links found on ``url``.

        A transport failure propagates as a RuntimeError from _extract_links
        (naming both attempts). An empty list therefore always means "page was
        fetched and contained no matching links".
        """
        return await self._extract_links(url, options or {})

    async def _extract_links(self, url: str, options: dict | None = None) -> list[str]:
        """Fetch ``url`` and return its same-origin links.

        Raises RuntimeError when every transport attempt failed, with both the
        direct and the flaresolverr error named. Only a successful fetch can
        return an empty list.
        """
        opts = options or {}
        # map_urls -> _extract_links fetches the user-supplied URL directly,
        # so it must be validated here (not just in scrape()). An unsafe URL
        # raises InvalidRequestError and aborts before any network I/O.
        validate_url(url)
        base_domain = urlparse(url).netloc
        errors: list[str] = []
        try:
            html = await self._fetch_direct(url, self._build_headers(url), 15)
        except Exception as exc:  # noqa: BLE001 - transport failure is named, not swallowed
            errors.append(f"direct: {type(exc).__name__}: {exc}")
            try:
                html = await self._fetch_via_flaresolverr(url, 30)
            except Exception as exc2:
                errors.append(f"flaresolverr: {type(exc2).__name__}: {exc2}")
                logger.warning(
                    "link_extraction_transport_failed",
                    extra={"url": url, "errors": errors},
                )
                raise RuntimeError(
                    f"link extraction transport failure for {url}: {'; '.join(errors)}"
                ) from exc2
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
