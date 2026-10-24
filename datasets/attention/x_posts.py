"""Pry — X (Twitter) public post lane.

``get_posts(kind, target, limit)`` fetches one X page and returns normalized
posts. Public profile timelines and single statuses/threads need no login;
``search`` does — X redirects an anonymous search to its onboarding/login
flow, which this module reports as ``login_wall`` with **zero** fabricated
posts.

Never raises. Every failure returns the full shape plus a machine ``error``
code and a human ``reason``:

======================  ==================================================
``unknown_kind``        ``kind`` is not one of :data:`x_templates.KINDS`
``invalid_target``      the handle/status id/query did not normalize
``fetch_failed``        transport error or non-200 answer from X
``login_wall``          X demanded a logged-in session for this page
``no_posts``            the page rendered but carried no posts
======================  ==================================================

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
from typing import Any

import httpx

from datasets.attention.x_parse import parse_posts
from datasets.attention.x_session import XSession
from datasets.attention.x_templates import (
    KINDS,
    LOGIN_MARKERS,
    build_url,
    normalize_target,
)
from pry.engine.webshare_proxy import next_webshare_proxy

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(connect=8.0, read=25.0, write=10.0, pool=8.0)
MAX_LIMIT = 100
DEFAULT_LIMIT = 20

_REASONS = {
    "unknown_kind": "kind must be one of: " + ", ".join(KINDS),
    "invalid_target": "target is not a valid handle, status id, or query",
    "fetch_failed": "X did not return a usable page",
    "login_wall": (
        "X requires a logged-in session for this page; set X_AUTH_TOKEN/CT0 "
        "(or X_COOKIE_HEADER) to scrape it — no posts were returned"
    ),
    "no_posts": "the page rendered but contained no posts (protected, suspended, or empty account)",
}


def _failure(kind: str, target: str, url: str, error: str, **extra: Any) -> dict[str, Any]:
    """Build the never-raise failure envelope."""
    payload: dict[str, Any] = {
        "kind": kind,
        "target": target,
        "url": url,
        "posts": [],
        "count": 0,
        "source": "none",
        "error": error,
        "reason": _REASONS.get(error, error),
    }
    payload.update(extra)
    logger.warning("x_posts_failed", extra={"kind": kind, "error": error})
    return payload


def _is_login_wall(final_url: str) -> bool:
    """True when X bounced the request to its login/onboarding flow."""
    return any(marker in (final_url or "") for marker in LOGIN_MARKERS)


async def _fetch(url: str, session: XSession, proxy: str | None) -> tuple[str, str, str]:
    """GET ``url``; return ``(html, final_url, error)`` and never raise."""
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT, headers=session.headers(), proxy=proxy, follow_redirects=True
        ) as client:
            response = await client.get(url)
    except (httpx.HTTPError, OSError) as exc:
        return "", url, f"{type(exc).__name__}: {str(exc)[:120]}"
    if response.status_code != httpx.codes.OK:
        return "", str(response.url), f"HTTP {response.status_code}"
    return response.text, str(response.url), ""


async def _fetch_with_egress(url: str, session: XSession) -> tuple[str, str, str]:
    """Fetch directly, then via one rotated residential proxy on failure."""
    proxies: list[str | None] = [session.proxy]
    if session.proxy is None:
        rotated = next_webshare_proxy("x.com")
        if rotated:
            proxies.append(rotated)
    error = ""
    for proxy in proxies:
        html, final_url, error = await _fetch(url, session, proxy)
        if not error:
            return html, final_url, ""
    return "", url, error


def _capped(limit: Any) -> int:
    """Clamp ``limit`` to the supported range; never raises."""
    try:
        return max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    except (TypeError, ValueError):
        return DEFAULT_LIMIT


def _select(kind: str, posts: list[dict[str, Any]], capped: int) -> list[dict[str, Any]]:
    """Apply the per-kind selection rule before truncation."""
    if kind == "status":
        return posts[:1]
    if kind == "thread":
        return posts[:capped]
    return posts


def _empty_code(kind: str, session: XSession) -> str:
    """A search with no posts is a login wall; anything else is genuinely empty."""
    return "login_wall" if kind == "search" and not session.authenticated else "no_posts"


async def get_posts(
    kind: str = "profile_timeline", target: str = "", limit: int = DEFAULT_LIMIT
) -> dict[str, Any]:
    """Fetch posts of ``kind`` for ``target``; never raises."""
    if kind not in KINDS:
        return _failure(kind, target, "", "unknown_kind")
    normalized = normalize_target(kind, target)
    if not normalized:
        return _failure(kind, target, "", "invalid_target")
    url = build_url(kind, normalized)
    capped = _capped(limit)

    session = XSession.from_env()
    html, final_url, error = await _fetch_with_egress(url, session)
    if error:
        return _failure(kind, normalized, url, "fetch_failed", detail=error, **session.masked())
    if _is_login_wall(final_url):
        return _failure(kind, normalized, url, "login_wall", **session.masked())

    posts, source = parse_posts(html)
    selected = _select(kind, posts, capped)[:capped]
    if not selected:
        code = _empty_code(kind, session)
        return _failure(kind, normalized, url, code, source=source, **session.masked())

    return {
        "kind": kind,
        "target": normalized,
        "url": final_url or url,
        "posts": selected,
        "count": len(selected),
        "source": source,
        **session.masked(),
    }
