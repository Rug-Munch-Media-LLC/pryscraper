"""US sportsbook proxy transport with cache and anti-bot handling."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import json
import logging
import random
import sys
import time
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)
_PROXY_TIMEOUT = 20.0
_TOR_TIMEOUT = 30.0
_HTTP_CACHE_TTL = 10.0
_http_cache: dict[str, tuple[float, Any]] = {}
_RNG = random.SystemRandom()
_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]
_BLOCK_MARKERS = (
    "incapsula",
    "_incapsula",
    "akamai",
    "access denied",
    "forbidden",
    "challenge",
    "just a moment",
    "checking your browser",
    "captcha",
    "too many requests",
    "you have been blocked",
)

try:
    from datasets.sports_data.odds import _SPORTS, _resolve_sports
except ImportError:  # pragma: no cover - parallel build guard
    _SPORTS = {}  # type: ignore[assignment]
    _resolve_sports = None  # type: ignore[assignment]

try:
    from pry.engine.tor_fallback import fetch_via_tor
except ImportError:  # pragma: no cover - optional dependency
    fetch_via_tor = None  # type: ignore[assignment]

try:
    from pry.engine.webshare_proxy import next_webshare_proxy
except ImportError:  # pragma: no cover - optional dependency
    next_webshare_proxy = None  # type: ignore[assignment]


def _monotonic() -> float:
    """Injectable clock for cache expiry (tests control time)."""
    return time.monotonic()


def _cache_enabled() -> bool:
    """Return False while an HTTP mock is active.

    Mirrors the repo convention (sports_data.odds/sources): when tests
    install mocks they expect every request to be observed, so the in-memory
    TTL cache is bypassed to avoid cross-test leakage.
    """
    respx_mod = sys.modules.get("respx")
    if respx_mod is None:
        return True
    return not bool(getattr(respx_mod, "routes", []))


def _clear_cache() -> None:
    """Drop all cached upstream responses (exposed for tests/tuning)."""
    _http_cache.clear()


def _stealth_headers(referer: str) -> dict[str, str]:
    """Browser-like request headers for the book JSON endpoints."""
    parsed = urlparse(referer)
    return {
        "User-Agent": _RNG.choice(_UA_POOL),
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": referer,
        "Origin": f"https://{parsed.netloc}",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }


def _looks_blocked(text: str | None) -> bool:
    """True when the body smells like an anti-bot interstitial."""
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _BLOCK_MARKERS)


async def _fetch_json_via_proxy(
    url: str,
    referer: str,
    *,
    proxy_provider: Any = None,
    tor_provider: Any = None,
) -> Any | None:
    """GET ``url`` (JSON) through Webshare US proxies, Tor fallback.

    Returns the parsed JSON object/array, or ``None`` on any failure —
    never raises. A non-200 response, an anti-bot interstitial, an empty
    body and a malformed JSON body all yield ``None`` (geo-block degrades
    to ``None`` exactly like a network failure).
    """
    key = url
    if _cache_enabled():
        entry = _http_cache.get(key)
        if entry is not None:
            cached_at, payload = entry
            if _monotonic() - cached_at < _HTTP_CACHE_TTL:
                return payload
            _http_cache.pop(key, None)
    payload = await _fetch_uncached_via_proxy(
        url, referer, proxy_provider=proxy_provider, tor_provider=tor_provider
    )
    if payload is not None and _cache_enabled():
        _http_cache[key] = (_monotonic(), payload)
    return payload


async def _fetch_uncached_via_proxy(
    url: str,
    referer: str,
    *,
    proxy_provider: Any = None,
    tor_provider: Any = None,
) -> Any | None:
    """Perform the actual proxied HTTP GET (no caching); never raises."""
    import aiohttp

    headers = _stealth_headers(referer)
    proxy_fn = proxy_provider or next_webshare_proxy
    tor_fn = tor_provider or fetch_via_tor
    proxy = proxy_fn() if proxy_fn is not None else None
    text: str | None = None
    try:
        if proxy:
            timeout = aiohttp.ClientTimeout(total=_PROXY_TIMEOUT)
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.get(url, headers=headers, proxy=proxy) as resp,
            ):
                if resp.status != 200:
                    return None
                text = await resp.text()
        elif tor_fn is not None:
            # Tor tier: rarely a US exit, so this usually cannot satisfy US
            # geo-fences — included as the honest last resort.
            text = await tor_fn(url, timeout=_TOR_TIMEOUT)
        else:
            return None
    except (aiohttp.ClientError, OSError, ValueError, TimeoutError):
        return None
    except Exception:  # noqa: BLE001 - contract: transport never raises
        logger.debug("us_books_proxy_fetch_error", extra={"url": url[:120]})
        return None
    if _looks_blocked(text):
        return None
    if not text or not text.strip():
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None
