"""Pry — resolve Google's opaque result redirects to real destinations."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import _HEADERS, _TIMEOUT

logger = logging.getLogger(__name__)


async def _resolve_google_redirects(
    results: list[dict[str, Any]], limit: int
) -> list[dict[str, Any]]:
    """Follow Google's opaque result redirects to the real target URL.

    Google wraps organic links as /goto?url=<opaque token>; the token is not
    decodable client-side so the URL must be obtained by following the
    redirect. Bounded to ``limit``; an unresolved entry keeps the Google URL
    rather than being dropped. Never raises.
    """
    with_redirects = [
        r
        for r in results
        if isinstance(r.get("url"), str)
        and "google." in r["url"]
        and ("/goto?" in r["url"] or "/url?" in r["url"])
    ]
    if not with_redirects:
        return results
    try:
        from pry.api.client import get_client

        client = await get_client()
    except (ImportError, RuntimeError, OSError) as exc:
        logger.warning("serp_resolver_unavailable", extra={"error": str(exc)[:160]})
        return results
    for entry in with_redirects[: max(limit, 1)]:
        try:
            resp = await client.get(
                entry["url"], headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True
            )
            final = str(resp.url)
            if final and "google." not in final:
                entry["url"] = final
        except httpx.HTTPError as exc:
            logger.warning("serp_redirect_resolve_failed", extra={"error": str(exc)[:160]})
    return results
