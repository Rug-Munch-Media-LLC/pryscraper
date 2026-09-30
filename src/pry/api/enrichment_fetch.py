"""SSRF-guarded source fetch for the enrichment pipeline.

``enrich_url`` accepts a caller-supplied URL (``POST /v1/enrich``,
``POST /v1/enrich/tech-stack``) and fetches it when no HTML was supplied, so the
fetch is an SSRF boundary. It lives here rather than inline in ``enrichment`` so
the pipeline module holds enrichment logic only, and it is the same guard the
router layer uses: :func:`pry.engine.fetch_guard.guard_get` validates the URL
before the first request AND re-validates every redirect hop.

The unguarded ``client.get(url, timeout=20, follow_redirects=True)`` this
replaced checked nothing after the first request, so a public open-redirector
turned an enrichment route into arbitrary internal network access (cloud
metadata at 169.254.169.254, loopback admin ports, RFC 1918 services).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging

import httpx

from pry.api.client import get_client
from pry.engine.fetch_guard import guard_get
from pry.core.errors import PryError

logger = logging.getLogger(__name__)

#: Per-request timeout for the enrichment fetch, matching the previous call.
FETCH_TIMEOUT_S = 20


async def fetch_enrichment_source(
    url: str, html: str = ""
) -> tuple[str, dict[str, str] | None, str | None]:
    """Return ``(html, headers, error)`` for enrichment of ``url``.

    Caller-supplied ``html`` short-circuits the fetch. Otherwise ``url`` is
    fetched through the SSRF guard.

    Args:
        url: The enrichment target. Caller-supplied, so it is validated.
        html: Already-fetched markup, if the caller supplied it.

    Returns:
        A ``(html, headers, error)`` triple. ``error`` is None on success, or a
        short reason when the URL was safe but the page could not be read.

    Raises:
        pry.core.errors.InvalidRequestError: Propagated from the guard when
            ``url`` or a redirect it returns is internal. It is a 400-class
            ``PryError``, so letting it out is what turns a refused URL into a
            4xx instead of a 500 — do NOT swallow it into ``error``.
    """
    if html:
        return html, None, None

    try:
        client = await get_client()
        resp = await guard_get(client, url, timeout=FETCH_TIMEOUT_S)
    except PryError as e:
        logger.warning("enrichment_url_rejected", extra={"url": url, "reason": e.message})
        raise
    except (httpx.HTTPError, httpx.RequestError) as e:
        # Transport-only failure: the URL passed the guard, the host was not
        # reachable. Never log the response body.
        logger.warning("enrichment_fetch_failed", extra={"url": url, "error": type(e).__name__})
        return "", None, f"fetch failed: {type(e).__name__}"

    if not resp.is_success:
        return "", None, f"fetch failed: HTTP {resp.status_code}"
    return resp.text, dict(resp.headers), None
