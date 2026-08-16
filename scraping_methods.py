"""Pry — additional scraping-method tiers for the intelligent fallback chain.

Adds three harder-target tiers that the fallback chain can use after the
existing network/browser tiers fail:

1. ``discover_json_api`` — Hidden-API discovery: scan a page's JS bundles
   (``<script src>``) and inline ``fetch()`` / ``axios()`` / ``/api/``
   references to find the JSON endpoints the frontend actually calls, then
   fetch those directly instead of scraping rendered HTML.
2. ``PersistentSession`` — Session persistence / cookie warmer: holds one
   ``httpx.AsyncClient`` (with a cookie jar) across calls, warms the site
   homepage first so the server sets a session cookie, then exposes
   ``fetch(url, params)``. Many sportsbook/retail JSON APIs only answer after
   that homepage visit.
3. ``fetch_rendered`` — Render-wait: load a JS SPA in Playwright (or
   Camoufox) and wait for network-idle / an optional selector before
   returning the rendered HTML — or the intercepted JSON responses via
   ``page.on("response")``.

Every public entry point is guarded (optional browser deps import-lazily)
and never raises: on any failure it returns ``None`` / ``[]`` so the fallback
chain can simply move to the next tier.

``METHODS`` describes each tier and when to use it.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from errors import InvalidRequestError
from url_guard import safe_get, validate_url

logger = logging.getLogger(__name__)

# Guarded optional browser dependencies — the module must import cleanly when
# neither Playwright nor Camoufox is installed (see pyproject `scrape` extra).
_HAS_PLAYWRIGHT = False
_HAS_CAMOUFOX = False
_HAS_CAMOUFOX_INTEGRATION = False
async_playwright: Any = None
AsyncCamoufox: Any = None
CamoufoxBrowser: Any = None

try:
    from playwright.async_api import async_playwright

    _HAS_PLAYWRIGHT = True
except ImportError:  # pragma: no cover - optional dependency
    pass

try:
    from camoufox import AsyncCamoufox as _CamoufoxAsyncClass

    AsyncCamoufox = _CamoufoxAsyncClass
    _HAS_CAMOUFOX = True
except ImportError:  # pragma: no cover - optional dependency
    pass

try:
    from camoufox_integration import CamoufoxBrowser

    _HAS_CAMOUFOX_INTEGRATION = True
except ImportError:  # pragma: no cover - optional dependency
    pass

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# ── Hidden-API discovery patterns ──────────────────────────────────────────
_SCRIPT_SRC_RE = re.compile(r"<script[^>]+src=[\"']([^\"']+)[\"']", re.IGNORECASE)
_FETCH_RE = re.compile(r"""fetch\s*\(\s*["']([^"']+)["']""")
_AXIOS_CALL_RE = re.compile(r"""axios(?:\.\w+)?\s*\(\s*["']([^"']+)["']""")
_AXIOS_OBJ_RE = re.compile(r"""axios\s*\(\s*\{[^}]*?url\s*:\s*["']([^"']+)["']""")
_XHR_RE = re.compile(r"""XMLHttpRequest\.open\s*\(\s*["'][^"']+["']\s*,\s*["']([^"']+)["']""")
_JQUERY_RE = re.compile(r"""\$\s*\.\s*(?:ajax|get|post|getJSON)\s*\(\s*["']([^"']+)["']""")
_API_PATH_RE = re.compile(r"""["']([^"']*/api/[^"']*)["']""", re.IGNORECASE)
_JSON_SUFFIX_RE = re.compile(r"""["']([^"']*\.json(?:[?#][^"']*)?)["']""", re.IGNORECASE)

# Raw references that never resolve to a JSON endpoint.
_SKIP_PREFIXES = ("data:", "javascript:", "blob:", "mailto:", "#", "about:")


def _resolve_candidate(raw: str, page_url: str) -> str | None:
    """Resolve a raw endpoint reference to an absolute http(s) URL."""
    candidate = raw.strip().strip("\"'")
    if not candidate or candidate.startswith(_SKIP_PREFIXES):
        return None
    try:
        resolved = urljoin(page_url, candidate)
    except ValueError:
        return None
    parsed = urlparse(resolved)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return resolved


def discover_json_api(page_url: str, html: str) -> list[str]:
    """Discover hidden JSON API endpoints from a page's HTML.

    Parses (a) inline ``fetch()`` / ``axios()`` / XHR / jQuery API calls,
    (b) quoted ``/api/...`` and ``.json`` path references, and (c) the JS
    bundle URLs referenced by ``<script src>`` — fetching and re-scanning
    those bundles surfaces the endpoints hidden inside them. All relative
    references are resolved against ``page_url``.

    Args:
        page_url: The URL the HTML was fetched from (used to resolve
            relative references).
        html: Raw page HTML (or an inline ``<script>`` body / JS bundle).

    Returns:
        De-duplicated, absolute candidate URLs, ordered by discovery
        (inline API calls first, then ``/api/`` / ``.json`` strings, then
        script bundles). Never raises: returns ``[]`` for unusable input.
    """
    if not isinstance(page_url, str) or not isinstance(html, str):
        return []
    page_url = page_url.strip()
    if not page_url or not html:
        return []

    raw_refs: list[str] = []
    for pattern in (
        _FETCH_RE,
        _AXIOS_CALL_RE,
        _AXIOS_OBJ_RE,
        _XHR_RE,
        _JQUERY_RE,
        _API_PATH_RE,
        _JSON_SUFFIX_RE,
    ):
        for match in pattern.finditer(html):
            if match.lastindex is None:
                continue
            raw_refs.append(match.group(1))
    # JS bundle URLs referenced by the page — scanning these surfaces the
    # endpoints hidden inside the bundles.
    raw_refs.extend(_SCRIPT_SRC_RE.findall(html))

    seen: set[str] = set()
    urls: list[str] = []
    for raw in raw_refs:
        resolved = _resolve_candidate(raw, page_url)
        if resolved is None or resolved in seen:
            continue
        seen.add(resolved)
        urls.append(resolved)
    return urls


# ── Session persistence / cookie warmer ────────────────────────────────────
class PersistentSession:
    """Async httpx session that reuses cookies across requests to one host.

    Many sportsbook / retail JSON APIs only answer after a homepage visit
    sets a session cookie. This wrapper holds a single ``httpx.AsyncClient``
    (with a cookie jar) across calls, warms the site homepage first, then
    exposes ``fetch(url, params)`` with cookie persistence.
    """

    def __init__(
        self,
        home_url: str | None = None,
        *,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
        proxy: str | None = None,
        transport: Any = None,
        max_redirects: int = 10,
    ) -> None:
        """Initialize the session.

        Args:
            home_url: Homepage to warm (collect cookies from). When omitted,
                derived from the first ``fetch()`` URL's origin.
            headers: Base headers sent on every request.
            timeout: httpx timeout in seconds.
            proxy: Optional proxy URL (e.g. ``http://user:pass@host:port``).
            transport: Optional httpx transport (used by tests / custom
                transports; ``None`` uses the default network transport).
            max_redirects: Hard cap on redirect hops (SSRF-safe re-validation).
        """
        self.home_url = home_url
        self.headers = dict(headers or {})
        self.timeout = timeout
        self.proxy = proxy
        self.transport = transport
        self.max_redirects = max_redirects
        self._client: httpx.AsyncClient | None = None
        self._warmed = False

    @staticmethod
    def _origin_of(url: str) -> str | None:
        """Return ``scheme://netloc/`` for an http(s) URL, else None."""
        try:
            parsed = urlparse(url)
        except ValueError:
            return None
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return None
        return f"{parsed.scheme}://{parsed.netloc}/"

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Create (or reuse) the httpx client with a persistent cookie jar."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=self.headers,
                timeout=self.timeout,
                proxy=self.proxy,
                cookies=httpx.Cookies(),
                transport=self.transport,
                follow_redirects=False,
            )
        return self._client

    @property
    def is_warmed(self) -> bool:
        """True once a homepage warm-up request has succeeded."""
        return self._warmed

    async def warmup(self) -> bool:
        """GET the site homepage so the server sets a session cookie.

        Returns:
            True when the warm-up request completed (any status); False when
            no homepage is configured or the request failed. Never raises.
        """
        if self._warmed:
            return True
        if not self.home_url:
            return False
        client = await self._ensure_client()
        try:
            await safe_get(client, self.home_url, max_redirects=self.max_redirects)
            self._warmed = True
            return True
        except (httpx.HTTPError, InvalidRequestError):
            return False
        except Exception:  # noqa: BLE001 - warmup is best-effort, never raises
            logger.debug("persistent_session_warmup_failed", exc_info=True)
            return False

    async def fetch(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response | None:
        """GET a URL reusing the session's cookies.

        Auto-warms the homepage on the first call (when a homepage is known
        or can be derived from ``url``'s origin).

        Args:
            url: Absolute http(s) URL to fetch.
            params: Optional query-string params for the request.

        Returns:
            The httpx.Response, or None on any failure. Never raises.
        """
        try:
            validate_url(url)
        except InvalidRequestError:
            return None
        client = await self._ensure_client()
        if not self._warmed:
            if self.home_url is None:
                origin = self._origin_of(url)
                if origin:
                    self.home_url = origin
            if self.home_url:
                await self.warmup()
        try:
            return await safe_get(client, url, params=params, max_redirects=self.max_redirects)
        except (httpx.HTTPError, InvalidRequestError):
            return None
        except Exception:  # noqa: BLE001 - fetch must never raise; a failed attempt is a None
            logger.debug("persistent_session_fetch_failed", exc_info=True)
            return None

    def cookies(self) -> dict[str, str]:
        """Snapshot of the cookie jar (for inspection / tests)."""
        if self._client is None:
            return {}
        return dict(self._client.cookies)

    async def close(self) -> None:
        """Close the underlying httpx client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def __aenter__(self) -> PersistentSession:
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.close()


# ── Render-wait (JS SPA) ────────────────────────────────────────────────────
def _pick_renderer(prefer: str) -> str:
    """Choose the browser backend for :func:`fetch_rendered`."""
    if prefer == "camoufox":
        return "camoufox"
    if prefer == "playwright":
        return "playwright"
    # auto: prefer the real Camoufox package when present, else Playwright.
    # The in-repo CamoufoxBrowser wrapper exists even without the package, but
    # it can't launch without it, so Playwright is the safer default.
    if _HAS_CAMOUFOX:
        return "camoufox"
    return "playwright"


async def _render_with_playwright(
    url: str,
    wait_ms: int,
    *,
    selector: str,
    proxy: str,
    collect_json: bool,
) -> str | None:
    """Render a page in Playwright; never raises (returns None on failure)."""
    if not _HAS_PLAYWRIGHT:
        return None
    try:
        json_bodies: list[str] = []

        async def _on_response(response: Any) -> None:
            content_type = response.headers.get("content-type", "")
            if "json" not in content_type.lower():
                return
            try:
                json_bodies.append(await response.text())
            except Exception:  # noqa: BLE001 - response capture is best-effort
                logger.debug("fetch_rendered_json_capture_failed", exc_info=True)

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            try:
                context_kwargs: dict[str, Any] = {
                    "user_agent": _DEFAULT_USER_AGENT,
                    "locale": "en-US",
                    "timezone_id": "America/New_York",
                }
                if proxy:
                    context_kwargs["proxy"] = {"server": proxy}
                context = await browser.new_context(**context_kwargs)
                page = await context.new_page()
                if collect_json:
                    page.on("response", lambda r: asyncio.create_task(_on_response(r)))
                await page.goto(url, wait_until="domcontentloaded", timeout=max(wait_ms, 30000))
                with contextlib.suppress(Exception):  # network-idle is best-effort
                    await page.wait_for_load_state("networkidle", timeout=wait_ms)
                if selector:
                    with contextlib.suppress(Exception):  # selector wait is best-effort
                        await page.wait_for_selector(selector, timeout=wait_ms)
                else:
                    await page.wait_for_timeout(min(wait_ms, 5000))
                if collect_json and json_bodies:
                    return json.dumps(json_bodies, ensure_ascii=False)
                return await page.content()
            finally:
                try:
                    await browser.close()
                except Exception:  # noqa: BLE001 - cleanup must not mask the original error
                    logger.debug("fetch_rendered_playwright_close_failed", exc_info=True)
    except Exception as e:  # noqa: BLE001 - browser tiers must never raise
        logger.debug("fetch_rendered_playwright_failed", extra={"error": str(e)[:80]})
        return None


async def _render_with_camoufox(
    url: str,
    wait_ms: int,
    *,
    selector: str,
    proxy: str,
    collect_json: bool,
) -> str | None:
    """Render a page in Camoufox; never raises (returns None on failure).

    Uses the real ``camoufox.AsyncCamoufox`` when the package is installed,
    otherwise falls back to the in-repo ``CamoufoxBrowser`` wrapper.
    """
    if _HAS_CAMOUFOX and AsyncCamoufox is not None:
        try:
            json_bodies: list[str] = []

            async def _on_response(response: Any) -> None:
                content_type = response.headers.get("content-type", "")
                if "json" not in content_type.lower():
                    return
                try:
                    json_bodies.append(await response.text())
                except Exception:  # noqa: BLE001 - response capture is best-effort
                    logger.debug("fetch_rendered_json_capture_failed", exc_info=True)

            async with AsyncCamoufox(headless=True) as browser:
                page = await browser.new_page()
                if collect_json:
                    page.on("response", lambda r: asyncio.create_task(_on_response(r)))
                await page.goto(url, wait_until="domcontentloaded")
                if selector:
                    with contextlib.suppress(Exception):  # selector wait is best-effort
                        await page.wait_for_selector(selector, timeout=wait_ms)
                else:
                    await page.wait_for_timeout(wait_ms)
                if collect_json and json_bodies:
                    return json.dumps(json_bodies, ensure_ascii=False)
                return await page.content()
        except Exception as e:  # noqa: BLE001 - browser tiers must never raise
            logger.debug("fetch_rendered_camoufox_failed", extra={"error": str(e)[:80]})
            # fall through to the in-repo wrapper
    if _HAS_CAMOUFOX_INTEGRATION and CamoufoxBrowser is not None:
        try:
            browser = CamoufoxBrowser()
            result = await browser.fetch(
                url,
                wait_selector=selector,
                wait_time=wait_ms,
                proxy=proxy,
            )
            if result.get("success"):
                content = result.get("content") or result.get("raw_html")
                return str(content) if content else None
        except Exception as e:  # noqa: BLE001 - browser tiers must never raise
            logger.debug("fetch_rendered_camoufox_wrapper_failed", extra={"error": str(e)[:80]})
    return None


async def fetch_rendered(
    url: str,
    wait_ms: int = 3000,
    *,
    selector: str = "",
    proxy: str = "",
    collect_json: bool = False,
    prefer: str = "auto",
) -> str | None:
    """Render a JS SPA in a real browser and return the rendered output.

    Loads ``url``, waits for network-idle (best-effort) plus an optional
    ``selector`` (or a bounded ``wait_ms``), then returns the rendered HTML.
    When ``collect_json`` is True and JSON API responses were intercepted via
    ``page.on("response")``, returns them as a JSON array string instead.

    Args:
        url: Absolute http(s) URL of the SPA.
        wait_ms: Network-idle / selector wait in milliseconds (default 3000).
        selector: Optional CSS selector to wait for before returning.
        proxy: Optional proxy URL for the browser context.
        collect_json: When True, prefer intercepted JSON responses over HTML.
        prefer: Browser backend — ``"auto"`` (default), ``"playwright"`` or
            ``"camoufox"``.

    Returns:
        Rendered HTML (or a JSON array string when ``collect_json`` matched),
        or None on any failure. Never raises.
    """
    try:
        validate_url(url)
    except InvalidRequestError:
        return None
    renderer = _pick_renderer(prefer)
    if renderer == "camoufox":
        return await _render_with_camoufox(
            url, wait_ms, selector=selector, proxy=proxy, collect_json=collect_json
        )
    return await _render_with_playwright(
        url, wait_ms, selector=selector, proxy=proxy, collect_json=collect_json
    )


# ── Tier registry for the fallback chain ────────────────────────────────────
METHODS: dict[str, dict[str, Any]] = {
    "hidden_api_discovery": {
        "name": "Hidden-API discovery",
        "callable": discover_json_api,
        "sync": True,
        "signature": "discover_json_api(page_url, html) -> list[str]",
        "when": (
            "Use after a page fetch succeeds but returns a JS shell — scan "
            "the HTML for the JSON endpoints the frontend calls, then fetch "
            "and JSON-parse each candidate instead of scraping rendered HTML."
        ),
        "cost": "free",
        "notes": (
            "Returns absolute candidate URLs (deduped). Fetch each with a "
            "PersistentSession; re-scan fetched JS bundles for deeper endpoints."
        ),
    },
    "persistent_session": {
        "name": "Session persistence / cookie warmer",
        "callable": PersistentSession,
        "sync": False,
        "signature": "PersistentSession(home_url).fetch(url, params) -> httpx.Response | None",
        "when": (
            "Use for JSON APIs that require a session cookie set by a prior "
            "homepage visit (sportsbook odds, retail catalog APIs) — warm the "
            "homepage once, then reuse the cookie jar across calls."
        ),
        "cost": "free",
        "notes": "Homepage derived from the first fetch URL when not configured.",
    },
    "render_wait": {
        "name": "Render-wait (JS SPA)",
        "callable": fetch_rendered,
        "sync": False,
        "signature": (
            "fetch_rendered(url, wait_ms=3000, *, selector='', proxy='', "
            "collect_json=False) -> str | None"
        ),
        "when": (
            "Use when content is rendered client-side with no JSON API, or "
            "when a JS challenge needs a real browser (network-idle wait). "
            "collect_json=True returns intercepted JSON responses as a string."
        ),
        "cost": "browser",
        "notes": "Playwright by default; Camoufox when prefer='camoufox' or the package is present.",
    },
}

__all__ = ["METHODS", "PersistentSession", "discover_json_api", "fetch_rendered"]
