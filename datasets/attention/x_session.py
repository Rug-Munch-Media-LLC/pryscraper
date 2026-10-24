"""Pry — X (Twitter) session and egress resolution.

X serves public profile/status pages over plain HTTP, but a *logged-in*
session is required for search and for the parts of a thread that are only
rendered to authenticated users. Credentials are read from the environment
and never logged:

* ``X_AUTH_TOKEN``     — the ``auth_token`` cookie value
* ``X_CT0``            — the ``ct0`` cookie value (CSRF token)
* ``X_COOKIE_HEADER``  — a full ``Cookie:`` header, takes precedence
* ``X_SCRAPE_PROXY``   — a literal proxy URL, or ``webshare``/``auto``/``pool``
  to rotate the residential pool via
  :func:`pry.engine.webshare_proxy.next_webshare_proxy`

A session with no credentials is still usable for public pages; it simply
cannot pass a login wall. Nothing here raises — a broken proxy resolver
degrades to a direct connection.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

AUTH_TOKEN_ENV = "X_AUTH_TOKEN"  # noqa: S105 - env var NAME, not a credential
CT0_ENV = "X_CT0"
COOKIE_HEADER_ENV = "X_COOKIE_HEADER"
PROXY_ENV = "X_SCRAPE_PROXY"

#: ``X_SCRAPE_PROXY`` values that mean "rotate the Webshare residential pool".
WEBSHARE_TOKENS = frozenset({"webshare", "auto", "pool", "rotate"})

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def _env(name: str) -> str:
    """Read an environment variable, stripped (empty string when unset)."""
    return (os.environ.get(name) or "").strip()


def resolve_proxy(raw: str) -> str | None:
    """Turn ``X_SCRAPE_PROXY`` into a proxy URL, or None for a direct request.

    ``webshare``/``auto``/``pool``/``rotate`` delegates to the shared
    residential rotation authority; anything else is used verbatim. A
    resolver failure degrades to a direct connection (never raises).
    """
    value = (raw or "").strip()
    if not value:
        return None
    if value.lower() in WEBSHARE_TOKENS:
        try:
            from pry.engine.webshare_proxy import next_webshare_proxy

            return next_webshare_proxy("x.com")
        except (ImportError, OSError, RuntimeError) as exc:
            logger.warning("x_proxy_resolve_failed", extra={"error": str(exc)[:120]})
            return None
    return value


@dataclass(frozen=True, slots=True)
class XSession:
    """Immutable X credentials + egress for one scrape."""

    auth_token: str = ""
    ct0: str = ""
    cookie_header: str = ""
    proxy: str | None = None
    lang: str = "en"

    @property
    def cookie(self) -> str:
        """Cookie header value: an explicit header wins over composed parts."""
        if self.cookie_header:
            return self.cookie_header
        parts = []
        if self.auth_token:
            parts.append(f"auth_token={self.auth_token}")
        if self.ct0:
            parts.append(f"ct0={self.ct0}")
        return "; ".join(parts)

    @property
    def authenticated(self) -> bool:
        """Whether this session can present a login-backed request."""
        return bool(self.auth_token or self.cookie_header)

    def headers(self) -> dict[str, str]:
        """Request headers for an X page fetch (never includes the cookie)."""
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": f"{self.lang},en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
        }
        cookie = self.cookie
        if cookie:
            headers["Cookie"] = cookie
        return headers

    def masked(self) -> dict[str, Any]:
        """Non-secret descriptor of this session, safe to log or return."""
        return {
            "authenticated": self.authenticated,
            "has_auth_token": bool(self.auth_token),
            "has_ct0": bool(self.ct0),
            "has_cookie_header": bool(self.cookie_header),
            "proxy": "configured" if self.proxy else "direct",
        }

    @classmethod
    def from_env(cls) -> XSession:
        """Build a session from the process environment."""
        lang = _env("X_LANG") or "en"
        return cls(
            auth_token=_env(AUTH_TOKEN_ENV),
            ct0=_env(CT0_ENV),
            cookie_header=_env(COOKIE_HEADER_ENV),
            proxy=resolve_proxy(_env(PROXY_ENV)),
            lang=lang.split("-")[0] or "en",
        )
