"""Pry — additional scraping-method tiers for the intelligent fallback chain.

Adds three harder-target tiers that the fallback chain can use after the
existing network/browser tiers fail, plus four more sync discovery tiers:

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
4. ``parse_feed`` / ``discover_feed`` — RSS/Atom feed parsing: fetch a feed
   URL and return structured entries (stdlib ``xml.etree``), or find the
   ``<link rel="alternate" type="application/rss+xml">`` from a page.
5. ``parse_sitemap`` / ``discover_sitemap`` — Sitemap-driven discovery:
   flatten sitemap XML / sitemap indexes into URLs, or locate the sitemap via
   ``robots.txt`` with a ``/sitemap.xml`` fallback.
6. ``discover_graphql`` / ``query_graphql`` — GraphQL endpoint discovery
   (Apollo / Hasura markers) and a guarded JSON POST query.
7. ``paginated_fetch`` — Rate-limit-aware paginated crawl of JSON list
   endpoints (``?page=N``) with a courtesy delay and stop-on-empty.

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
import time
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from pry.core.errors import InvalidRequestError
from pry.engine.url_guard import safe_get, validate_redirect_url, validate_url

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
    from pry.engine.camoufox_integration import CamoufoxBrowser

    _HAS_CAMOUFOX_INTEGRATION = True
except ImportError:  # pragma: no cover - optional dependency
    pass

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# ── Shared sync network helpers ─────────────────────────────────────────────
# The sync tiers below need a guarded, never-raising httpx layer. Redirects
# are followed manually so every Location target is re-validated (mirrors
# ``url_guard.safe_get`` for sync callers).


def _sync_fetch(
    url: str,
    *,
    method: str = "GET",
    params: dict[str, Any] | None = None,
    json_body: Any = None,
    timeout: float = 20.0,
) -> httpx.Response | None:
    """SSRF-guarded, never-raising synchronous httpx request.

    Validates the initial URL (and every redirect ``Location`` target) with
    :func:`url_guard.validate_url`, so private/loopback/metadata hosts are
    rejected before any network I/O. Any failure returns ``None``.

    Args:
        url: Absolute http(s) URL to request.
        method: HTTP method (``"GET"`` or ``"POST"``).
        params: Optional query-string params for the request.
        json_body: Optional JSON body (sent with ``json=``).
        timeout: httpx timeout in seconds.

    Returns:
        The final httpx.Response, or None on any failure. Never raises.
    """
    try:
        validate_url(url)
    except InvalidRequestError:
        return None
    try:
        with httpx.Client(follow_redirects=False, timeout=timeout) as client:
            response = client.request(method, url, params=params, json=json_body)
            redirects = 0
            while response.is_redirect and redirects < 10:
                location = response.headers.get("location")
                if not location:
                    break
                target = urljoin(str(response.url), location)
                try:
                    validate_redirect_url(target)
                except InvalidRequestError:
                    return None
                response = client.request(method, target, json=json_body)
                redirects += 1
            return response
    except (httpx.HTTPError, InvalidRequestError):
        return None
    except Exception:
        logger.debug("sync_fetch_failed", extra={"url": url[:120]}, exc_info=True)
        return None


def _sync_get(url: str, *, params: dict[str, Any] | None = None) -> httpx.Response | None:
    """Guarded synchronous GET (see :func:`_sync_fetch`)."""
    return _sync_fetch(url, method="GET", params=params)


def _sync_post(url: str, *, json_body: Any = None) -> httpx.Response | None:
    """Guarded synchronous POST (see :func:`_sync_fetch`)."""
    return _sync_fetch(url, method="POST", json_body=json_body)


def _origin_of(url: str) -> str | None:
    """Return ``scheme://netloc/`` for an http(s) URL, else None."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}/"


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
        except Exception:
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
        except Exception:
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
            except Exception:
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
                except Exception:
                    logger.debug("fetch_rendered_playwright_close_failed", exc_info=True)
    except Exception as e:
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
                except Exception:
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
        except Exception as e:
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
        except Exception as e:
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


# ── RSS/Atom feed parsing ───────────────────────────────────────────────────
_FEED_TAG_RE = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
_FEED_REL_ALTERNATE_RE = re.compile(r"""rel\s*=\s*["']alternate["']""", re.IGNORECASE)
_FEED_TYPE_RE = re.compile(r"""type\s*=\s*["']application/(?:rss|atom)\+xml["']""", re.IGNORECASE)
_FEED_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)


def _localname(tag: str) -> str:
    """Strip the ``{namespace}`` prefix from an XML tag name."""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def _rss_entries(root: ET.Element) -> list[dict[str, str]]:
    """Extract RSS 2.0 ``<item>`` entries as flat dicts."""
    channel = next((child for child in root if _localname(child.tag) == "channel"), None)
    if channel is None:
        return []
    entries: list[dict[str, str]] = []
    for item in channel:
        if _localname(item.tag) != "item":
            continue
        entry = {"title": "", "link": "", "summary": "", "published": ""}
        for field in item:
            name = _localname(field.tag)
            text = (field.text or "").strip()
            if name == "title":
                entry["title"] = text
            elif name == "link":
                entry["link"] = text
            elif name == "description":
                entry["summary"] = text
            elif name == "pubDate":
                entry["published"] = text
        entries.append(entry)
    return entries


def _atom_entries(root: ET.Element) -> list[dict[str, str]]:
    """Extract Atom ``<entry>`` elements as flat dicts."""
    entries: list[dict[str, str]] = []
    for child in root:
        if _localname(child.tag) != "entry":
            continue
        entry = {"title": "", "link": "", "summary": "", "published": ""}
        for field in child:
            name = _localname(field.tag)
            if name == "title":
                entry["title"] = (field.text or "").strip()
            elif name == "link":
                href = field.attrib.get("href")
                if href:
                    entry["link"] = href.strip()
            elif name in ("summary", "content") and not entry["summary"]:
                entry["summary"] = (field.text or "").strip()
            elif name in ("published", "updated") and not entry["published"]:
                entry["published"] = (field.text or "").strip()
        entries.append(entry)
    return entries


def parse_feed(url: str) -> list[dict[str, str]]:
    """Fetch and parse an RSS 2.0 or Atom feed into structured entries.

    Args:
        url: Absolute http(s) URL of the feed.

    Returns:
        A list of entries, each with the keys ``title``, ``link``,
        ``summary`` and ``published`` (empty string when a field is absent).
        Atom ``<content>`` / ``<updated>`` fall back to ``summary`` /
        ``published`` when ``<summary>`` / ``<published>`` are missing.
        Never raises: returns ``[]`` for unusable input, fetch or parse
        failures.
    """
    if not isinstance(url, str) or not url.strip():
        return []
    response = _sync_get(url)
    if response is None:
        return []
    try:
        # Feed XML is untrusted; parsing is best-effort and failures return [].
        # (stdlib xml.etree mandated by spec — no defusedxml dep.)
        root = ET.fromstring(response.text)  # noqa: S314
    except (ET.ParseError, ValueError):
        return []
    root_name = _localname(root.tag)
    if root_name == "rss":
        return _rss_entries(root)
    if root_name == "feed":
        return _atom_entries(root)
    return []


def discover_feed(page_url: str, html: str) -> str | None:
    """Find the RSS/Atom feed URL advertised by a page.

    Scans for ``<link rel="alternate" type="application/rss+xml|atom+xml">``
    (attribute order-insensitive) and resolves the ``href`` against
    ``page_url``.

    Args:
        page_url: The URL the HTML was fetched from.
        html: Raw page HTML.

    Returns:
        The absolute feed URL, or None when no alternate feed link is found.
        Never raises.
    """
    if not isinstance(page_url, str) or not isinstance(html, str):
        return None
    page_url = page_url.strip()
    if not page_url or not html:
        return None
    for tag in _FEED_TAG_RE.findall(html):
        if not _FEED_REL_ALTERNATE_RE.search(tag) or not _FEED_TYPE_RE.search(tag):
            continue
        match = _FEED_HREF_RE.search(tag)
        if match is None:
            continue
        resolved = _resolve_candidate(match.group(1), page_url)
        if resolved is not None:
            return resolved
    return None


# ── Sitemap-driven discovery ────────────────────────────────────────────────
_MAX_SITEMAP_DEPTH = 2
_MAX_SITEMAP_FETCHES = 20


def _walk_sitemap(url: str, out: list[str], seen: set[str], *, depth: int) -> None:
    """Fetch a sitemap, flattening sitemap indexes into the ``out`` list.

    Bounded by :data:`_MAX_SITEMAP_DEPTH` and :data:`_MAX_SITEMAP_FETCHES`;
    ``seen`` prevents re-fetching the same sitemap URL (cycle safety).
    """
    if depth > _MAX_SITEMAP_DEPTH or len(seen) >= _MAX_SITEMAP_FETCHES:
        return
    if url in seen:
        return
    seen.add(url)
    response = _sync_get(url)
    if response is None:
        return
    try:
        # Sitemap XML is untrusted; parsing is best-effort and bounded.
        # (stdlib xml.etree mandated by spec — no defusedxml dep.)
        root = ET.fromstring(response.text)  # noqa: S314
    except (ET.ParseError, ValueError):
        return
    locs = [
        child.text.strip()
        for child in root.iter()
        if _localname(child.tag) == "loc" and child.text and child.text.strip()
    ]
    if _localname(root.tag) == "sitemapindex":
        for nested in locs[: _MAX_SITEMAP_FETCHES - len(seen)]:
            _walk_sitemap(nested, out, seen, depth=depth + 1)
        return
    for loc in locs:
        if loc not in out:
            out.append(loc)


def parse_sitemap(url: str) -> list[str]:
    """Fetch and parse a sitemap (``urlset``) or sitemap index.

    A ``<sitemapindex>`` is flattened by recursively fetching each referenced
    sub-sitemap (bounded recursion, cycle-safe); a ``<urlset>`` contributes
    its ``<url><loc>`` entries directly.

    Args:
        url: Absolute http(s) URL of the sitemap or sitemap index.

    Returns:
        De-duplicated list of URLs found in the sitemap, or ``[]`` on any
        failure. Never raises.
    """
    if not isinstance(url, str) or not url.strip():
        return []
    urls: list[str] = []
    _walk_sitemap(url, urls, set(), depth=0)
    return urls


def discover_sitemap(domain: str) -> str | None:
    """Locate a sitemap URL for a domain via ``robots.txt``.

    Fetches ``<origin>/robots.txt`` and returns the first ``Sitemap:`` line.
    When robots.txt is unreachable or has no ``Sitemap:`` line, falls back to
    the conventional ``<origin>/sitemap.xml`` URL.

    Args:
        domain: A bare domain (``example.com``) or a full http(s) URL; a bare
            domain is normalized to ``https://``.

    Returns:
        The absolute sitemap URL, or None for unusable input. Never raises.
    """
    if not isinstance(domain, str) or not domain.strip():
        return None
    domain = domain.strip()
    if "://" not in domain:
        domain = f"https://{domain}"
    try:
        parsed = urlparse(domain)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    base = f"{parsed.scheme}://{parsed.netloc}"
    robots_url = f"{base}/robots.txt"
    response = _sync_get(robots_url)
    if response is not None:
        for line in response.text.splitlines():
            stripped = line.strip()
            if not stripped.lower().startswith("sitemap:"):
                continue
            value = stripped.split(":", 1)[1].strip()
            if value:
                resolved = _resolve_candidate(value, robots_url)
                if resolved is not None:
                    return resolved
    fallback = f"{base}/sitemap.xml"
    return fallback if _resolve_candidate(fallback, base) is not None else None


# ── GraphQL endpoint discovery ──────────────────────────────────────────────
_GRAPHQL_QUOTED_RE = re.compile(
    r"""["']([^"']*(?:graphql|apollo|hasura|gql)[^"']*)["']""", re.IGNORECASE
)
_GRAPHQL_URI_ATTR_RE = re.compile(
    r"""(?:uri|endpoint|url)\s*[:=]\s*["']([^"']*)["']""", re.IGNORECASE
)
_GRAPHQL_SCRIPT_SRC_RE = re.compile(r"""<script[^>]+src=["']([^"']+)["']""", re.IGNORECASE)
_GRAPHQL_BUNDLE_MARKERS = ("graphql", "gql", "apollo", "hasura")
_HASURA_ATTR_RE = re.compile(r"data-hasura-[a-z0-9-]+", re.IGNORECASE)
_APOLLO_STATE_MARKER = "__APOLLO_STATE__"


def discover_graphql(page_url: str, html: str) -> list[str]:
    """Discover GraphQL endpoint candidates from a page's HTML.

    Scans (a) quoted references containing ``graphql`` / ``apollo`` /
    ``hasura`` / ``gql`` (e.g. ``"/graphql"``), (b) Apollo-style
    ``uri:`` / ``endpoint:`` / ``url:`` configuration, (c) ``<script src>``
    bundle URLs that look GraphQL-related, and (d) convention markers: a
    ``data-hasura-*`` attribute implies the standard ``/v1/graphql`` endpoint
    on the page origin and an ``__APOLLO_STATE__`` marker implies the standard
    ``/graphql`` endpoint. All relative references resolve against
    ``page_url``.

    Args:
        page_url: The URL the HTML was fetched from.
        html: Raw page HTML.

    Returns:
        De-duplicated, absolute candidate URLs (ordered by discovery).
        Never raises: returns ``[]`` for unusable input.
    """
    if not isinstance(page_url, str) or not isinstance(html, str):
        return []
    page_url = page_url.strip()
    if not page_url or not html:
        return []

    candidates: list[str] = []
    for match in _GRAPHQL_QUOTED_RE.finditer(html):
        if match.lastindex is None:
            continue
        value = match.group(1).strip()
        if value:
            candidates.append(value)
    for match in _GRAPHQL_URI_ATTR_RE.finditer(html):
        if match.lastindex is None:
            continue
        value = match.group(1).strip()
        if value and any(marker in value.lower() for marker in _GRAPHQL_BUNDLE_MARKERS):
            candidates.append(value)
    for src in _GRAPHQL_SCRIPT_SRC_RE.findall(html):
        lowered = src.lower()
        if any(marker in lowered for marker in _GRAPHQL_BUNDLE_MARKERS):
            candidates.append(src)
    origin = _origin_of(page_url)
    if origin is not None:
        if _HASURA_ATTR_RE.search(html):
            candidates.append(urljoin(origin, "/v1/graphql"))
        if _APOLLO_STATE_MARKER in html:
            candidates.append(urljoin(origin, "/graphql"))

    seen: set[str] = set()
    urls: list[str] = []
    for raw in candidates:
        resolved = _resolve_candidate(raw, page_url)
        if resolved is None or resolved in seen:
            continue
        seen.add(resolved)
        urls.append(resolved)
    return urls


def query_graphql(
    endpoint: str,
    query: str,
    variables: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """POST a GraphQL query to an endpoint and return the JSON payload.

    Sends ``{"query": query, "variables": variables or {}}`` as JSON. The
    endpoint is SSRF-validated before the request.

    Args:
        endpoint: Absolute http(s) GraphQL endpoint URL.
        query: GraphQL query document.
        variables: Optional variables dict (defaults to ``{}``).

    Returns:
        The parsed JSON payload when the response is valid JSON, else None.
        Never raises.
    """
    if not isinstance(endpoint, str) or not isinstance(query, str):
        return None
    if not endpoint.strip() or not query.strip():
        return None
    response = _sync_post(endpoint, json_body={"query": query, "variables": variables or {}})
    if response is None:
        return None
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


# ── Rate-limit-aware paginated crawl ────────────────────────────────────────
_JSON_LIST_KEYS = ("results", "data", "items")


def _json_list_items(response: httpx.Response) -> list[dict[str, Any]]:
    """Extract a JSON list (or a list under ``results``/``data``/``items``)."""
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in _JSON_LIST_KEYS:
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def paginated_fetch(
    url: str,
    page_param: str = "page",
    max_pages: int = 5,
    per_page_delay: float = 0.5,
) -> list[dict[str, Any]]:
    """Fetch a JSON list endpoint across pages until empty.

    GETs ``url`` with ``page_param`` set to 1, 2, … up to ``max_pages``,
    sleeping ``per_page_delay`` seconds between requests (rate-limit
    courtesy), and stops early when a page returns no items. Pages are
    expected to be JSON lists; dict payloads are also unwrapped from the
    common ``results`` / ``data`` / ``items`` keys.

    Args:
        url: Absolute http(s) URL of the JSON list endpoint.
        page_param: Query-string parameter name for the page number.
        max_pages: Hard cap on the number of pages fetched.
        per_page_delay: Seconds to sleep between page requests.

    Returns:
        The concatenated items across pages, or ``[]`` on any failure.
        Never raises.
    """
    if not isinstance(url, str) or not url.strip():
        return []
    page_count = max(int(max_pages), 1)
    collected: list[dict[str, Any]] = []
    for page in range(1, page_count + 1):
        response = _sync_get(url, params={page_param: page})
        if response is None:
            break
        items = _json_list_items(response)
        if not items:
            break
        collected.extend(items)
        if page < page_count and per_page_delay > 0:
            time.sleep(per_page_delay)
    return collected


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
    "feed_parsing": {
        "name": "RSS/Atom feed parsing",
        "callable": parse_feed,
        "sync": True,
        "signature": "parse_feed(url) -> list[dict] (+ discover_feed(page_url, html) -> str | None)",
        "when": (
            "Use when a site publishes an RSS/Atom feed (news, blogs, podcast "
            "shows, changelogs): discover_feed finds the <link rel=alternate> "
            "from a page, parse_feed returns structured entries."
        ),
        "cost": "free",
        "notes": "Stdlib xml.etree — no extra deps. Entries carry title/link/summary/published.",
    },
    "sitemap_discovery": {
        "name": "Sitemap-driven discovery",
        "callable": parse_sitemap,
        "sync": True,
        "signature": "parse_sitemap(url) -> list[str] (+ discover_sitemap(domain) -> str | None)",
        "when": (
            "Use to enumerate all URLs of a site: discover_sitemap finds the "
            "sitemap via robots.txt (or /sitemap.xml), parse_sitemap flattens "
            "urlset and sitemap-index XML into URLs."
        ),
        "cost": "free",
        "notes": "Bounded recursion (depth 2, max 20 fetches) and cycle-safe.",
    },
    "graphql_discovery": {
        "name": "GraphQL endpoint discovery",
        "callable": discover_graphql,
        "sync": True,
        "signature": (
            "discover_graphql(page_url, html) -> list[str] "
            "(+ query_graphql(endpoint, query, variables) -> dict | None)"
        ),
        "when": (
            "Use when a site is powered by GraphQL (Apollo / Hasura): "
            "discover_graphql scans HTML for endpoint candidates, "
            "query_graphql POSTs a query JSON-style."
        ),
        "cost": "free",
        "notes": "POST body: {'query': ..., 'variables': {...}}; SSRF-validated; never raises.",
    },
    "paginated_crawl": {
        "name": "Rate-limit-aware paginated crawl",
        "callable": paginated_fetch,
        "sync": True,
        "signature": (
            "paginated_fetch(url, page_param='page', max_pages=5, per_page_delay=0.5) -> list[dict]"
        ),
        "when": (
            "Use for JSON list APIs served in pages (?page=N): fetches pages "
            "with a courtesy delay between requests and stops on an empty page."
        ),
        "cost": "free",
        "notes": "Unwraps results/data/items keys from dict payloads; never raises.",
    },
}

__all__ = [
    "METHODS",
    "PersistentSession",
    "discover_feed",
    "discover_graphql",
    "discover_json_api",
    "discover_sitemap",
    "fetch_rendered",
    "paginated_fetch",
    "parse_feed",
    "parse_sitemap",
    "query_graphql",
]
