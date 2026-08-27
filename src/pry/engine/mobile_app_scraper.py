# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
"""Pry — Mobile App API Scraper (Tier 14).

Scrapes mobile app APIs by impersonating Android/iOS clients.
Many websites have mobile apps that expose APIs with weaker protection.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Mobile app user agents
MOBILE_USER_AGENTS = [
    # Android Chrome
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
    # iPhone Safari
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    # Android Firefox
    "Mozilla/5.0 (Android 13; Mobile; rv:127.0) Gecko/127.0 Firefox/127.0",
    # iPhone Chrome
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/125.0.0.0 Mobile/15E148 Safari/604.1",
]

# Common mobile API endpoints
MOBILE_API_PATTERNS = [
    "/api/v1/",
    "/api/v2/",
    "/api/mobile/",
    "/api/v1.0/",
    "/api/v1.1/",
    "/graphql",
    "/api/graphql",
]


class MobileAppScraper:
    """Scrape mobile app APIs by impersonating mobile clients."""

    def __init__(self):
        self._ua_index = 0

    def is_available(self) -> bool:
        return True

    async def scrape(self, url: str, opts: dict[str, Any] | None = None) -> str | None:
        """Scrape via mobile API endpoints."""
        try:
            import httpx

            opts = opts or {}
            parsed = urlparse(url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"

            # Try common mobile API patterns
            ua = self._rotate_ua()
            headers = {
                "User-Agent": ua,
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "X-Mobile-App": "true",
            }

            async with httpx.AsyncClient(timeout=30) as client:
                # Try to discover API endpoints
                for pattern in MOBILE_API_PATTERNS:
                    try:
                        api_url = f"{base_url}{pattern}"
                        resp = await client.get(api_url, headers=headers)
                        if resp.is_success and len(resp.text) > 100:
                            return resp.text
                    except Exception:
                        continue

            return None
        except Exception as e:
            logger.debug("mobile_app_scraper_failed", extra={"error": str(e)[:50]})
            return None

    def _rotate_ua(self) -> str:
        ua = MOBILE_USER_AGENTS[self._ua_index % len(MOBILE_USER_AGENTS)]
        self._ua_index += 1
        return ua


from urllib.parse import urlparse
