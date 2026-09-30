"""SSRF-guarded fetch for the router layer — the single place routers fetch.

Lives in ``pry.api`` rather than under a router package: the import-linter
"Domain independence" contract forbids one router domain importing another, and
guard_get is now shared by ``scraping`` and ``ai``.

Every router that fetches a user-supplied URL goes through :func:`guard_get`
instead of calling ``client.get`` directly. The routers accept an arbitrary
URL by design (Pry scrapes public web pages), so the SSRF boundary belongs in
one small module rather than being re-implemented per route.

``guard_get`` delegates to :func:`pry.engine.url_guard.safe_get`, which
validates the initial URL and re-validates every ``Location`` target before the
next hop. A bare ``client.get`` — especially with ``follow_redirects=True`` —
validates nothing after the first request, so a public open-redirector turns a
scraping route into arbitrary internal network access (cloud metadata at
169.254.169.254, loopback admin ports, RFC 1918 services).

``follow_redirects`` is deliberately not a parameter: exposing it would let a
caller reintroduce exactly the bug this module exists to prevent.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import TYPE_CHECKING

from pry.engine.url_guard import safe_get

if TYPE_CHECKING:
    import httpx

#: Default UA for direct-HTML fetches (matches the shared client default).
DEFAULT_USER_AGENT = "Pry/3.0"

#: UA for fetches of pages that only serve markup to a browser (Cloudflare).
BROWSER_USER_AGENT = "Mozilla/5.0"


async def guard_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    # ASYNC109: forwarded verbatim to httpx, whose per-request timeout is the
    # documented way to bound a call; asyncio.timeout cannot be injected here
    # because safe_get owns the whole request/redirect loop.
    timeout: float = 15,  # noqa: ASYNC109
    user_agent: str = DEFAULT_USER_AGENT,
) -> httpx.Response:
    """GET ``url`` with SSRF validation on the initial URL and every redirect.

    Raises:
        pry.core.errors.InvalidRequestError: If ``url`` or any redirect target
            is a private/loopback/link-local address, an internal hostname, a
            non-HTTP(S) scheme, or contains path-traversal sequences. Nothing is
            fetched in that case.
    """
    return await safe_get(
        client,
        url,
        timeout=timeout,
        headers={"User-Agent": user_agent},
    )
