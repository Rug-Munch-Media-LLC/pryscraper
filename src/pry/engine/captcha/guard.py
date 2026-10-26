"""Pry — hard exclusions for CAPTCHA solving.

Two refusals survive the "solve everything" directive:

* ``blocked.robots``   — the path is disallowed by the site's robots.txt.
* ``skipped.paid_api`` — the URL is a paid/logged-in API endpoint; a solver is
  never applied there (it would burn solver credit and leak credentials).

Everything else may be attempted by the ladder.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
from urllib.parse import parse_qsl, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

logger = logging.getLogger(__name__)

_ROBOTS_CACHE: dict[str, RobotFileParser | None] = {}
_PAID_PATH_PREFIXES = ("/api/", "/v1/", "/v2/", "/v3/", "/graphql")
_PAID_QUERY_KEYS = {
    "api_key",
    "apikey",
    "access_token",
    "token",
    "key",
    "secret",
    "client_secret",
}
_ROBOTS_TIMEOUT_S = 5.0


def is_paid_api(url: str) -> bool:
    """True when ``url`` is an API/authenticated endpoint we must not solve."""
    parts = urlsplit(url)
    if parts.path.lower().startswith(_PAID_PATH_PREFIXES):
        return True
    return any(k.lower() in _PAID_QUERY_KEYS for k, _ in parse_qsl(parts.query))


async def _robots_for(origin: str) -> RobotFileParser | None:
    """Fetch and cache robots.txt for ``origin``; None when unavailable."""
    if origin in _ROBOTS_CACHE:
        return _ROBOTS_CACHE[origin]
    parser: RobotFileParser | None = None
    try:
        async with httpx.AsyncClient(timeout=_ROBOTS_TIMEOUT_S, follow_redirects=True) as client:
            resp = await client.get(f"{origin}/robots.txt")
        if resp.is_success:
            parser = RobotFileParser()
            parser.parse(resp.text.splitlines())
    except httpx.HTTPError as exc:
        logger.info("captcha_robots_unavailable origin=%s error=%s", origin, exc)
    _ROBOTS_CACHE[origin] = parser
    return parser


async def solver_allowed(url: str) -> tuple[bool, str]:
    """Decide whether any solver may touch ``url``.

    Returns ``(allowed, reason)`` where reason is ``"allowed"``,
    ``"blocked.robots"`` or ``"skipped.paid_api"``.
    """
    if is_paid_api(url):
        return False, "skipped.paid_api"
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    parser = await _robots_for(origin)
    if parser is not None and not parser.can_fetch("*", url):
        return False, "blocked.robots"
    return True, "allowed"
