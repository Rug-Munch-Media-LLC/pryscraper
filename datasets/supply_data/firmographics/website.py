"""Company website discovery and anti-bot detection."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
import os

import httpx

from datasets.supply_data.firmographics.http import _fetch_once

logger = logging.getLogger(__name__)
_WEBSITE_ENV = "PRY_FIRMO_WEBSITE"
_WEBSITE_CANDIDATES = ("{slug}.com", "{slug}.io", "{slug}.co", "{slug}.ai")
_ANTI_BOT_MARKERS = (
    "cf-challenge",
    "checking your browser",
    "attention required",
    "unusual traffic",
    "access denied",
    "captcha",
)


async def _find_website(slug: str) -> str | None:
    """Return the first reachable website URL for a company slug."""
    override = os.environ.get(_WEBSITE_ENV, "").strip()
    if override:
        return override if override.startswith(("http://", "https://")) else f"https://{override}"
    for candidate in _WEBSITE_CANDIDATES:
        url = f"https://{candidate.format(slug=slug)}"
        try:
            response = await _fetch_once(url)
            if 200 <= response.status_code < 400:
                return str(response.url)
        except (httpx.HTTPError, OSError):
            logger.debug("firmographics_website_probe_failed", exc_info=True, extra={"url": url})
    return None


def _is_anti_bot_page(html: str) -> bool:
    lowered = html.lower()
    return any(marker in lowered for marker in _ANTI_BOT_MARKERS)
