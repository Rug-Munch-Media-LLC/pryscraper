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

from pry.engine.body_limits import MAX_RESPONSE_BYTES, cap_bytes
from pry.engine.tiers_base import _get_shared_client, _us_flag
from pry.engine.tiers_special_delegated import TierDelegatedMixin
from pry.engine.url_guard import safe_get

logger = logging.getLogger(__name__)

__all__ = [
    "_GOOGLE_INTERSTITIAL_MARKERS",
    "TierDelegatedMixin",
    "TierSpecialMixin",
    "_is_google_interstitial",
]
# Markers that identify a Google interstitial / search / consent page rather
# than the requested cached document. Google's webcache endpoint frequently
# redirects to a search or consent page (or returns one with HTTP 200) when
# the cache entry is gone or the caller is not signed in. Returning such a
# page as scraped content is a silent data-integrity bug: the caller gets a
# fake success whose body is Google's UI, not the target site.
_GOOGLE_INTERSTITIAL_MARKERS: tuple[str, ...] = (
    "webcache.googleusercontent.com",
    "consent.google.com",
    "consent.youtube.com",
    "google.com/search",
    "google.com/webhp",
    "google.com/preferences",
    "sorry/index",
    "our systems have detected unusual traffic",
    "unusual traffic from your computer network",
    "to continue, please click",
    "before you continue to google",
    # Google discontinued webcache (2024): the endpoint now serves a
    # "not redirected within a few seconds" notice page with HTTP 200.
    "not redirected within a few seconds",
    "trouble accessing google search",
    'id="captcha-form"',
    "id='captcha-form'",
    "g-recaptcha",
)


def _is_google_interstitial(html: str) -> bool:
    """True when ``html`` is a Google search/consent/interstitial page.

    The webcache tier must never treat these as a successful cache hit. The
    check is deliberately marker-based (not URL-based) because the tier only
    receives the response body, and Google serves these pages with HTTP 200.
    """
    lower = html.lower()
    return any(marker in lower for marker in _GOOGLE_INTERSTITIAL_MARKERS)


class TierSpecialMixin(TierDelegatedMixin):
    """Special-purpose scraping tiers (bots, archives, Tor, external scrapers).

    ``TierDelegatedMixin`` is the BASE, so the AI-visual / mobile / GraphQL
    tiers resolve through the normal mixin chain and ``self._tier_*`` still
    yields the identical function object the ladder binds.
    """

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
                # Google serves search/consent/interstitial pages with HTTP 200
                # when the cache entry is missing. Reject them: a fake success
                # here poisons every downstream consumer with Google's UI.
                if _is_google_interstitial(r.text):
                    logger.debug(
                        "google_cache_interstitial_rejected",
                        extra={"url": url, "reason": "google_interstitial_page"},
                    )
                    return None
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
                    # Stream with a hard byte ceiling: ``resp.text()`` buffers
                    # the whole body, so one oversize .onion response could
                    # exhaust the worker.
                    chunks: list[bytes] = []
                    total = 0
                    truncated = False
                    async for chunk in resp.content.iter_chunked(65536):
                        room = MAX_RESPONSE_BYTES - total
                        if len(chunk) > room:
                            chunks.append(chunk[:room])
                            total = MAX_RESPONSE_BYTES
                            truncated = True
                            break
                        chunks.append(chunk)
                        total += len(chunk)
                    body, capped = cap_bytes(b"".join(chunks), url)
                    if truncated or capped:
                        opts["pry_truncated"] = True
                    return body.decode(resp.charset or "utf-8", errors="replace")
        except Exception as e:
            # Deliberately broad, and it must stay the LAST handler. Two real
            # failures escape a narrower `except aiohttp.ClientError`:
            #
            # 1. This try BEGINS with `import aiohttp`. If that import fails, or
            #    the installed aiohttp is version-skewed, the pre-bound
            #    `aiohttp` is still None -- so evaluating the except clause
            #    raises AttributeError from inside the handler itself. That
            #    escapes the tier, and _attempt_tier's catch-all turns it into
            #    an indistinguishable tier failure, silently burning the rest
            #    of the fallback chain.
            # 2. A malformed TOR_SOCKS5_PORT is reported by from_url as a plain
            #    ValueError, which a ClientError handler never catches.
            #
            # The contract that makes the broad catch safe: a tier returns a
            # value and never raises, because the chain has no per-tier error
            # channel. None is the typed failure, and it can never be promoted
            # to a success (the orchestrator gates on
            # `bool(html and self._is_valid(html))`).
            logger.debug("tor_failed", extra={"error": str(e)[:200]})
        return None
