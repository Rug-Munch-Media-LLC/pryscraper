"""Special tier implementations (googlebot, archive, google cache, tor, ai visual, mobile app, graphql).

Part of the ``TierMixin`` composition in :mod:`pry.engine.tiers`.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import quote

import httpx

from pry.engine.tiers_base import _get_shared_client, _us_flag
from pry.engine.url_guard import safe_get

logger = logging.getLogger(__name__)


class TierSpecialMixin:
    """Special-purpose scraping tiers (bots, archives, Tor, external scrapers)."""

    async def _tier_googlebot(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        try:
            headers = self._build_headers(url)
            headers["User-Agent"] = (
                "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
            )
            # Proxy is client-level httpx config; only a dedicated client is
            # needed when a proxy is set. The no-proxy path reuses the shared
            # pooled client (get_client).
            if proxy_url:
                async with httpx.AsyncClient(timeout=30, proxy=proxy_url) as c:
                    r = await safe_get(c, url, headers=headers)
            else:
                c = await _get_shared_client()
                r = await safe_get(c, url, headers=headers, timeout=30)
            if r.is_success:
                return r.text
        except (httpx.HTTPError, httpx.RequestError) as e:
            logger.debug("googlebot_failed", extra={"error": str(e)[:200]})
        return None

    async def _tier_archive(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        """Fetch from Wayback Machine CDX API for latest snapshot."""
        try:
            # URL-encode the target before embedding it in the CDX query param
            # and the archive path. An unencoded query string (e.g. ?a=1&b=2)
            # would corrupt the surrounding URL (the & becomes a param separator
            # in the CDX call and breaks the /web/{ts}id_/ path entirely).
            target = quote(url, safe="")
            cdx_url = f"https://web.archive.org/cdx/search/cdx?url={target}&output=json&limit=1&fl=timestamp,original"
            c = await _get_shared_client()
            r = await c.get(cdx_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            if r.is_success:
                data = r.json()
                if len(data) > 1:
                    timestamp = data[1][0]
                    archive_url = f"https://web.archive.org/web/{timestamp}id_/{target}"
                    ar = await safe_get(c, archive_url, timeout=30)
                    if ar.is_success:
                        return ar.text
        except (httpx.HTTPError, httpx.RequestError) as e:
            logger.debug("archive_failed", extra={"error": str(e)[:200]})
        return None

    async def _tier_google_cache(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        try:
            # Same encoding requirement as the archive tier: an unencoded
            # query string would be parsed as extra params of the cache URL.
            target = quote(url, safe="")
            cache_url = f"https://webcache.googleusercontent.com/search?q=cache:{target}"
            c = await _get_shared_client()
            r = await safe_get(c, cache_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            if r.is_success:
                return r.text
        except (httpx.HTTPError, httpx.RequestError) as e:
            logger.debug("google_cache_failed", extra={"error": str(e)[:200]})
        return None

    async def _tier_tor(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        """Fetch via Tor SOCKS5 proxy."""
        if not _us_flag("_has_tor"):
            return None
        aiohttp: Any = None
        ProxyConnector: Any = None  # noqa: N806 - class binding mirrors import
        try:
            import aiohttp
            from aiohttp_socks import ProxyConnector

            tor_host = os.getenv("TOR_SOCKS5_HOST", "127.0.0.1")
            tor_port = os.getenv("TOR_SOCKS5_PORT", "9050")
            connector = ProxyConnector.from_url(f"socks5://{tor_host}:{tor_port}")
            async with (
                aiohttp.ClientSession(connector=connector) as session,
                session.get(
                    url,
                    headers=self._build_headers(url),
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp,
            ):
                if resp.status == 200:
                    return await resp.text()
        except aiohttp.ClientError as e:
            logger.debug("tor_failed", extra={"error": str(e)[:200]})
        return None

    async def _tier_ai_visual(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        """Tier 13: AI Visual Scraper — screenshot + LLM vision extraction."""
        if not _us_flag("_has_ai_visual") or not _us_flag("_ai_visual"):
            return None
        try:
            return await _us_flag("_ai_visual").scrape(url, opts)
        except Exception as e:
            logger.debug("ai_visual_failed", extra={"error": str(e)[:200]})
        return None

    async def _tier_mobile_app(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        """Tier 14: Mobile App API — impersonate mobile clients."""
        if not _us_flag("_has_mobile") or not _us_flag("_mobile_scraper"):
            return None
        try:
            return await _us_flag("_mobile_scraper").scrape(url, opts)
        except Exception as e:
            logger.debug("mobile_app_failed", extra={"error": str(e)[:200]})
        return None

    async def _tier_graphql(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        """Tier 15: GraphQL API Discovery — find and query GraphQL endpoints."""
        if not _us_flag("_has_graphql") or not _us_flag("_graphql_scraper"):
            return None
        try:
            return await _us_flag("_graphql_scraper").scrape(url, opts)
        except Exception as e:
            logger.debug("graphql_failed", extra={"error": str(e)[:200]})
        return None
