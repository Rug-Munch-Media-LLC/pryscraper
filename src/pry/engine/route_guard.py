"""Pry — Playwright SSRF route guard.

Playwright follows redirects internally, so a ``302 -> 169.254.169.254``
would bypass validation done only on the initial URL. Every network request
(including each redirect hop) passes through this handler and is re-validated
before continuing. Non-network schemes (``data:``, ``blob:``, ``about:``, ...)
never touch the network and are allowed through.

Used by every Playwright/Camoufox path that navigates to a caller-supplied
URL: ``tiers_browser``, ``methods/render``, ``actions``, ``cookie_warmer``,
``ai_visual_scraper`` and the Camoufox integration.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlparse

from pry.core.errors import InvalidRequestError
from pry.engine.url_guard import validate_url

logger = logging.getLogger(__name__)

_NETWORK_SCHEMES = frozenset({"http", "https"})


async def guard_route(route: Any) -> None:
    """Abort a Playwright route whose request targets an SSRF-sensitive host.

    Playwright calls this for the initial request and for every redirect hop,
    so a redirect into a private range is aborted before it is sent.
    """
    request_url = route.request.url
    try:
        parsed = urlparse(request_url)
    except ValueError:
        logger.warning("silent_exception_swallowed", exc_info=True)
        await route.abort()
        return
    if parsed.scheme not in _NETWORK_SCHEMES:
        # Non-network scheme (data:, blob:, about:) — no SSRF surface.
        await route.continue_()
        return
    try:
        # DNS resolution is synchronous; keep it off the event loop.
        await asyncio.to_thread(validate_url, request_url)
    except InvalidRequestError:
        logger.warning("route_ssrf_blocked", extra={"url": request_url})
        await route.abort()
        return
    await route.continue_()


def install_route_guard(target: Any) -> None:
    """Install :func:`guard_route` on a Playwright page or context.

    ``route("**/*", handler)`` intercepts every request including redirects.
    A page inherits its context's routes, so installing on the context is
    enough; installing on both is harmless (first handler wins per request).
    """
    target.route("**/*", guard_route)


__all__ = ["guard_route", "install_route_guard"]
