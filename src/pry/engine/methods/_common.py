"""Shared helpers for the per-method scraping tiers.

Contains the guarded sync network layer, URL-resolution helpers, the default
user agent, and the optional browser-dependency flags (Playwright / Camoufox).
The module must import cleanly when neither browser package is installed.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from pry.core.errors import InvalidRequestError
from pry.engine.url_guard import validate_redirect_url, validate_url

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
except ImportError as e:  # pragma: no cover - optional dependency
    logger.debug("scraping_methods_optional_import_unavailable", extra={"error": str(e)[:160]})

try:
    from camoufox import AsyncCamoufox as _CamoufoxAsyncClass

    AsyncCamoufox = _CamoufoxAsyncClass
    _HAS_CAMOUFOX = True
except ImportError as e:  # pragma: no cover - optional dependency
    logger.debug("scraping_methods_optional_import_unavailable", extra={"error": str(e)[:160]})

try:
    from pry.engine.camoufox_integration import CamoufoxBrowser  # noqa: F401 - availability probe

    _HAS_CAMOUFOX_INTEGRATION = True
except ImportError as e:  # pragma: no cover - optional dependency
    logger.debug("scraping_methods_optional_import_unavailable", extra={"error": str(e)[:160]})

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Raw references that never resolve to a JSON endpoint.
_SKIP_PREFIXES = ("data:", "javascript:", "blob:", "mailto:", "#", "about:")


# ── Shared sync network helpers ─────────────────────────────────────────────
# The sync tiers need a guarded, never-raising httpx layer. Redirects are
# followed manually so every Location target is re-validated (mirrors
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
        logger.warning("silent_exception_swallowed", exc_info=True)
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
                    logger.warning("silent_exception_swallowed", exc_info=True)
                    return None
                response = client.request(method, target, json=json_body)
                redirects += 1
            return response
    except (httpx.HTTPError, InvalidRequestError):
        logger.warning("silent_exception_swallowed", exc_info=True)
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
        logger.warning("silent_exception_swallowed", exc_info=True)
        return None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}/"


def _resolve_candidate(raw: str, page_url: str) -> str | None:
    """Resolve a raw endpoint reference to an absolute http(s) URL."""
    candidate = raw.strip().strip("\"'")
    if not candidate or candidate.startswith(_SKIP_PREFIXES):
        return None
    try:
        resolved = urljoin(page_url, candidate)
    except ValueError:
        logger.warning("silent_exception_swallowed", exc_info=True)
        return None
    parsed = urlparse(resolved)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return resolved


def _localname(tag: str) -> str:
    """Strip the ``{namespace}`` prefix from an XML tag name."""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


__all__ = [
    "_DEFAULT_USER_AGENT",
    "_HAS_CAMOUFOX",
    "_HAS_CAMOUFOX_INTEGRATION",
    "_HAS_PLAYWRIGHT",
    "_SKIP_PREFIXES",
    "_localname",
    "_origin_of",
    "_resolve_candidate",
    "_sync_fetch",
    "_sync_get",
    "_sync_post",
    "async_playwright",
    "logger",
]
