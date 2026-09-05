"""Transport layer for the sportsbook registry scrapers.

Reuses Pry's own stack instead of inventing a 6th HTTP client:

* plain httpx + stealth headers + retry (the ``sports_data.sources``
  pattern, with :func:`retry.async_retry`);
* escalation to :class:`ultimate_scraper.UltimateScraper` (Pry's intelligent
  fallback: httpx -> TLS impersonation -> cloudscraper -> FlareSolverr ->
  Camoufox -> Playwright -> Tor -> premium proxy -> archive) for browser-tier
  or geo-fenced books;
* Webshare residential proxies via :mod:`webshare_proxy`
  (``WEBSHARE_PROXY_LIST``) for books marked ``geo_required``.

Every function here is best-effort: failures return ``None`` and never
propagate to callers.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import contextlib
import importlib.util
import logging
import random
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from pry.engine.retry import RetryConfig, async_retry

logger = logging.getLogger(__name__)

_RNG = random.SystemRandom()

_HTTP_TIMEOUT = httpx.Timeout(30.0)
_RETRY_CONFIG = RetryConfig(
    max_retries=1,
    base_delay=0.1,
    max_delay=0.4,
    retryable_exceptions=(httpx.HTTPError,),
)

_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
]

# ── Guarded reuse of Pry's own stack (never a hard dependency) ───────────
_UltimateScraper: Any = None
if importlib.util.find_spec("pry.engine.ultimate_scraper") is not None:
    from pry.engine.ultimate_scraper import UltimateScraper as _UltimateScraper

_ULTIMATE: Any = None  # lazily instantiated UltimateScraper singleton


def _ultimate_instance() -> Any | None:
    """Lazily build the UltimateScraper singleton (guarded, never raises)."""
    global _ULTIMATE
    if _ULTIMATE is not None:
        return _ULTIMATE
    if _UltimateScraper is None:
        return None
    with contextlib.suppress(Exception):
        _ULTIMATE = _UltimateScraper()
    return _ULTIMATE


def _headers(url: str) -> dict[str, str]:
    """Browser-like request headers (rotate UA, sec-fetch, referer)."""
    parsed = urlparse(url)
    return {
        "User-Agent": _RNG.choice(_UA_POOL),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": _RNG.choice(["en-US,en;q=0.9", "en-GB,en;q=0.8", "en-US,en;q=0.7"]),
        "Referer": f"https://{parsed.netloc}/",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Upgrade-Insecure-Requests": "1",
        "Connection": "keep-alive",
    }


def _geo_proxy() -> str | None:
    """Next Webshare residential proxy (``WEBSHARE_PROXY_LIST``), or None."""
    try:
        from pry.engine.webshare_proxy import next_webshare_proxy

        return next_webshare_proxy()
    except Exception:  # noqa: BLE001 - proxy pool is best-effort
        return None


def _looks_blocked(text: str) -> bool:
    """True when the body smells like an anti-bot interstitial."""
    lowered = (text or "").lower()
    markers = (
        "cf-chl",
        "challenge-platform",
        "just a moment",
        "checking your browser",
        "attention required",
        "access denied",
        "captcha",
        "forbidden",
        "too many requests",
    )
    return any(marker in lowered for marker in markers)


async def _plain_fetch(url: str, proxy: str | None = None) -> str | None:
    """Plain httpx GET (stealth headers + retry); None on any failure."""

    async def _one() -> str:
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT,
            proxy=proxy,
            follow_redirects=True,
            headers=_headers(url),
        ) as client:
            response = await client.get(url)
            if response.status_code >= 500:
                response.raise_for_status()
            text = response.text
        if not text:
            raise ValueError("empty upstream response")
        return text

    try:
        return await async_retry(_one, config=_RETRY_CONFIG)
    except Exception:  # noqa: BLE001 - never raise out of the transport
        return None


async def _scrape_with_ultimate(url: str, *, browser: bool, geo_required: bool) -> str | None:
    """Escalate through UltimateScraper's intelligent fallback chain.

    Pry's 12-tier stack (httpx -> TLS impersonation -> cloudscraper ->
    FlareSolverr -> Camoufox -> Playwright -> Tor -> premium proxy ->
    archive) is the escalation path; proxy resolution is handled internally
    by ProxyManager/Webshare. Returns the rendered HTML or None.
    """
    scraper = _ultimate_instance()
    if scraper is None:
        return None
    try:
        opts: dict[str, Any] = {"timeout": 45, "use_premium_proxy_first": geo_required}
        result = await scraper.scrape(url, opts)
        if isinstance(result, dict) and result.get("status") == "ok":
            html = result.get("raw_html")
            if isinstance(html, str) and html:
                return html
    except Exception:  # noqa: BLE001 - escalation is best-effort
        logger.debug("books_ultimate_failed", extra={"url": url})
    return None


def _render_url(template: str, sport: str) -> str:
    """Fill the ``{sport}`` placeholder (and return the URL unchanged if absent)."""
    slug = re.sub(r"[^a-z0-9_\-/]", "-", str(sport).strip().lower())
    return template.replace("{sport}", slug)
