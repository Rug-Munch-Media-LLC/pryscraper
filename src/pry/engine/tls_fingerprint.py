"""Pry — TLS Fingerprint Impersonation using curl_cffi.
This is the SINGLE BIGGEST BOTTLE-NECK in modern scraping. Sites like Cloudflare,
Akamai, DataDome, and PerimeterX use TLS fingerprinting (JA3/JA4) to detect bots.
curl_cffi can impersonate real browser TLS handshakes, bypassing these checks."""

# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).

import asyncio
import logging
import time
from typing import Any
from urllib.parse import urljoin

from pry.engine.url_guard import validate_redirect_url, validate_url

logger = logging.getLogger(__name__)

# Redirect statuses followed manually so every hop is SSRF-revalidated.
_REDIRECT_STATUS = frozenset({301, 302, 303, 307, 308})
_MAX_REDIRECTS = 10

# Check if curl_cffi is available
AsyncSession: Any = None
try:
    from curl_cffi.requests import AsyncSession

    _has_curl_cffi = True
except ImportError:
    logger.warning("silent_exception_swallowed", exc_info=True)
    _has_curl_cffi = False

# Browser fingerprints that curl_cffi can impersonate
BROWSER_FINGERPRINTS = [
    "chrome",
    "chrome99",
    "chrome100",
    "chrome101",
    "chrome104",
    "chrome107",
    "chrome110",
    "chrome116",
    "chrome119",
    "chrome120",
    "chrome123",
    "chrome124",
    "chrome131",
    "chrome133",
    "chrome99_android",
    "chrome131_android",
    "edge",
    "edge99",
    "edge101",
    "edge122",
    "edge127",
    "firefox",
    "firefox109",
    "firefox117",
    "firefox120",
    "firefox123",
    "firefox124",
    "firefox132",
    "safari",
    "safari15_3",
    "safari15_5",
    "safari16_5",
    "safari17_0",
    "safari17_2_ios",
    "tor",
]


class TLSScraper:
    """Scraper that uses curl_cffi to impersonate real browser TLS fingerprints.
    Bypasses JA3/JA4 fingerprinting that blocks 80%+ of bot traffic."""

    def __init__(self, default_impersonate: str = "chrome131"):
        self.default_impersonate = (
            default_impersonate if default_impersonate in BROWSER_FINGERPRINTS else "chrome"
        )
        if not _has_curl_cffi:
            logger.warning(
                "curl_cffi_not_installed",
                extra={"hint": "pip install curl_cffi"},
            )

    async def fetch(
        self,
        url: str,
        impersonate: str = "",
        headers: dict[str, str] | None = None,
        proxy: str = "",
        timeout_s: int = 30,
        cookies: dict[str, str] | None = None,
        follow_redirects: bool = True,
    ) -> dict[str, Any]:
        """Fetch a URL with TLS fingerprint impersonation.

        Args:
            url: The URL to fetch
            impersonate: Browser fingerprint to impersonate (e.g., "chrome131", "firefox132", "safari17_0")
            headers: Additional HTTP headers
            proxy: Proxy URL (e.g., "http://user:pass@proxy.example.com:8080")
            timeout_s: Request timeout in seconds
            cookies: Cookies to send with the request
            follow_redirects: Whether to follow HTTP redirects

        Returns: {status_code, text, headers, cookies, url, elapsed}
        """
        if not _has_curl_cffi:
            return {
                "success": False,
                "error": "curl_cffi not installed. Run: pip install curl_cffi",
            }

        impersonate = impersonate or self.default_impersonate
        if impersonate not in BROWSER_FINGERPRINTS:
            impersonate = "chrome"

        default_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        if headers:
            default_headers.update(headers)

        try:
            start = time.time()
            validate_url(url)
            current_url = url
            async with AsyncSession(
                impersonate=impersonate,  # type: ignore[arg-type]  # curl_cffi uses Literal union; runtime validated
                headers=default_headers,
                cookies=cookies or {},
                proxy=proxy or None,
                timeout=timeout_s,
                # Redirects are followed manually below so every Location
                # hop is re-validated against SSRF targets before the next
                # request (curl_cffi's built-in follow would skip validation).
                allow_redirects=False,
            ) as session:
                resp: Any = None
                redirects = 0
                while True:
                    resp = await session.get(current_url)
                    if (
                        not follow_redirects
                        or resp.status_code not in _REDIRECT_STATUS
                        or "location" not in resp.headers
                        or redirects >= _MAX_REDIRECTS
                    ):
                        break
                    location = resp.headers["location"]
                    target = urljoin(str(resp.url), location)
                    validate_redirect_url(target)
                    current_url = target
                    redirects += 1
                elapsed = time.time() - start
                return {
                    "success": True,
                    "status_code": resp.status_code,
                    "text": resp.text,
                    "content": resp.content,
                    "headers": dict(resp.headers),
                    "cookies": dict(resp.cookies),
                    "url": str(resp.url),
                    "elapsed": round(elapsed, 2),
                    "impersonate": impersonate,
                }
        except (
            Exception
        ) as e:  # curl_cffi raises heterogeneous exceptions; dict-contract error path
            logger.warning("silent_exception_swallowed", exc_info=True)
            return {
                "success": False,
                "error": str(e)[:300],
                "impersonate": impersonate,
            }

    async def fetch_with_rotation(
        self,
        url: str,
        fingerprints: list[str] | None = None,
        headers: dict[str, str] | None = None,
        proxy: str = "",
        timeout_s: int = 30,
    ) -> dict[str, Any]:
        """Try multiple browser fingerprints until one succeeds (anti-fingerprint rotation)."""
        fingerprints = fingerprints or BROWSER_FINGERPRINTS[:10]
        for fp in fingerprints:
            result = await self.fetch(
                url, impersonate=fp, headers=headers, proxy=proxy, timeout_s=timeout_s
            )
            if result.get("success") and result.get("status_code", 0) < 400:
                result["matched_fingerprint"] = fp
                return result
        return {
            "success": False,
            "error": "All fingerprints failed",
            "attempts": len(fingerprints),
        }

    def is_available(self) -> bool:
        return _has_curl_cffi


async def _test_fetch() -> None:
    """Smoke test: verifies the scraper can be instantiated and is_available works."""
    s = TLSScraper()
    logger.info("tls_scraper_available", extra={"available": s.is_available()})


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_test_fetch())
