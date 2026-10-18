"""Simple HTTP tier implementations (direct, premium proxy, cloudscraper, flaresolverr).

Part of the ``TierMixin`` composition in :mod:`pry.engine.tiers`.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from pry.engine.body_limits import (
    MAX_JSON_ENVELOPE_BYTES,
    MAX_RESPONSE_BYTES,
    cap_bytes,
    cap_httpx_stream,
    cap_text,
)
from pry.engine.tiers_base import _get_shared_client, _us_flag
from pry.engine.url_guard import safe_get

logger = logging.getLogger(__name__)


class TierHTTPMixin:
    """Simple HTTP-based scraping tiers."""

    async def _tier_direct(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        try:
            # Proxy is a client-level httpx config (not a per-request param), so
            # a dedicated client is required only when a proxy is in play. The
            # common no-proxy path reuses the shared pooled client (get_client)
            # so connections are kept alive across requests.
            if proxy_url:
                async with httpx.AsyncClient(timeout=30, proxy=proxy_url) as c:
                    r = await safe_get(c, url, headers=self._build_headers(url))
            else:
                c = await _get_shared_client()
                r = await safe_get(c, url, headers=self._build_headers(url), timeout=30)
            if r.is_success:
                return r.text
        except (httpx.HTTPError, httpx.RequestError) as e:
            logger.debug("direct_failed", extra={"error": str(e)[:200]})
        return None

    async def _tier_premium_proxy(
        self, url: str, proxy_url: str, opts: dict[str, Any]
    ) -> str | None:
        """Fetch via the configured premium residential/datacenter proxy."""
        try:
            # This tier exists solely to route through the premium proxy, and
            # proxy is a client-level httpx config (not a per-request param).
            # A dedicated client is therefore required here — the shared pooled
            # client cannot carry a per-request proxy.
            async with httpx.AsyncClient(timeout=45, proxy=proxy_url) as c:
                r = await safe_get(c, url, headers=self._build_headers(url))
                if r.is_success:
                    return r.text
        except (httpx.HTTPError, httpx.RequestError) as e:
            logger.debug("premium_proxy_failed", extra={"error": str(e)[:200]})
        return None

    async def _tier_cloudscraper(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        if not _us_flag("_has_cloudscraper"):
            return None
        try:
            import cloudscraper

            def _do_fetch() -> tuple[str | None, bool]:
                # cloudscraper's API is synchronous/blocking (create_scraper +
                # get). It runs inside asyncio.to_thread so it does not block
                # the event loop — same pattern as _tier_undetected.
                scraper = cloudscraper.create_scraper(
                    browser={"browser": "chrome", "platform": "windows", "mobile": False}
                )
                resp = scraper.get(
                    url,
                    timeout=30,
                    headers={"User-Agent": self._rotate_ua()},
                    stream=True,
                )
                try:
                    if resp.status_code != 200:
                        return None, False
                    # Stream, don't buffer: a hostile body must never be
                    # materialised in full before the cap is applied.
                    chunks: list[bytes] = []
                    total = 0
                    truncated = False
                    for chunk in resp.iter_content(chunk_size=65536):
                        if not chunk:
                            continue
                        room = MAX_RESPONSE_BYTES - total
                        if len(chunk) > room:
                            chunks.append(chunk[:room])
                            total = MAX_RESPONSE_BYTES
                            truncated = True
                            break
                        chunks.append(chunk)
                        total += len(chunk)
                    body, capped = cap_bytes(b"".join(chunks), url)
                    text = body.decode(resp.encoding or "utf-8", errors="replace")
                    return text, truncated or capped
                finally:
                    resp.close()

            text, truncated = await asyncio.to_thread(_do_fetch)
            if truncated:
                # Tier contract is ``-> str | None``; ``opts`` is the only
                # per-request metadata channel, so flag it there.
                opts["pry_truncated"] = True
            return text
        except Exception as e:
            logger.debug("cloudscraper_failed", extra={"error": str(e)[:200]})
        return None

    async def _tier_flaresolverr(
        self, url: str, opts: dict[str, Any], proxy_url: str | None = None
    ) -> str | None:
        from pry.core.settings import settings

        if not settings.flaresolverr_url:
            return None
        try:
            payload = {"cmd": "request.get", "url": url, "maxTimeout": 60000}
            c = await _get_shared_client()
            # Stream the JSON envelope: ``r.json()`` would buffer an unbounded
            # body (a hostile page is escaped into the envelope and can be
            # orders of magnitude larger than the page itself).
            async with c.stream(
                "POST",
                settings.flaresolverr_url,
                json=payload,
                timeout=60,
            ) as r:
                if not r.is_success:
                    # Surface the transport-level failure (e.g. 500 from the
                    # sidecar) instead of silently returning None with no reason.
                    logger.debug(
                        "flaresolverr_http_error",
                        extra={"status": r.status_code, "url": url},
                    )
                    return None
                body, envelope_truncated = await cap_httpx_stream(
                    r, max_bytes=MAX_JSON_ENVELOPE_BYTES
                )
            data = json.loads(body)
            solution = data.get("solution", {})
            if solution.get("status") == 200:
                text, capped = cap_text(
                    str(solution.get("response") or ""), url, max_bytes=MAX_RESPONSE_BYTES
                )
                if capped or envelope_truncated:
                    opts["pry_truncated"] = True
                return text
            # FlareSolverr reached (HTTP 200) but could not solve the target:
            # log its own status/message so the failure reason is visible.
            logger.debug(
                "flaresolverr_unsolved",
                extra={
                    "solution_status": solution.get("status"),
                    "flare_message": str(data.get("message", ""))[:200],
                    "url": url,
                },
            )
        except (httpx.HTTPError, httpx.RequestError, ValueError, TimeoutError) as e:
            # ValueError covers a JSON envelope cut at MAX_JSON_ENVELOPE_BYTES;
            # TimeoutError covers an asyncio-level hung sidecar.
            logger.debug("flaresolverr_failed", extra={"error": str(e)[:200]})
        return None
