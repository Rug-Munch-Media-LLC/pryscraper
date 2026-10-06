"""Pry — Camoufox SSRF route guard.

Playwright's ``page.route`` handler for Camoufox. The browser follows
redirects internally, so a ``302 -> 169.254.169.254`` would otherwise bypass
URL validation. Every network request (including each redirect hop) passes
through this handler and is re-validated before continuing. Non-network
schemes (``data:``, ``blob:``, ``about:``, ...) never touch the network and
are allowed through.
"""

# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from pry.core.errors import InvalidRequestError
from pry.engine.url_guard import validate_url

logger = logging.getLogger(__name__)


async def guard_route(route: Any) -> None:
    """Abort a Playwright route whose request targets an SSRF-sensitive host."""
    request_url = route.request.url
    try:
        parsed = urlparse(request_url)
    except ValueError:
        logger.warning("silent_exception_swallowed", exc_info=True)
        await route.abort()
        return
    if parsed.scheme not in {"http", "https"}:
        # Non-network scheme (data:, blob:, about:) — no SSRF surface.
        await route.continue_()
        return
    try:
        validate_url(request_url)
    except InvalidRequestError:
        logger.warning("camoufox_ssrf_blocked", extra={"url": request_url})
        await route.abort()
        return
    await route.continue_()
