"""Session persistence / cookie warmer tier — one httpx.AsyncClient across calls."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from pry.core.errors import InvalidRequestError
from pry.engine.methods._common import logger
from pry.engine.url_guard import safe_get, validate_url


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
            logger.warning("silent_exception_swallowed", exc_info=True)
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
            logger.warning("silent_exception_swallowed", exc_info=True)
            return False
        except Exception:  # noqa: BLE001 - never-raise guard
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
            logger.warning("silent_exception_swallowed", exc_info=True)
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
            logger.warning("silent_exception_swallowed", exc_info=True)
            return None
        except Exception:  # noqa: BLE001 - never-raise guard
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


__all__ = ["PersistentSession"]
