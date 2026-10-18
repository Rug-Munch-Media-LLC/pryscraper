"""SSRF-safe HTTP fetching: capped body reads and pinned redirect hops.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

from pry.engine.url_guard.url_validate import validate_redirect_url

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)

# Hard ceiling on a single response body (5 MiB). Without it every tier held
# the entire body in memory, so one multi-GB response could OOM the worker.
MAX_RESPONSE_BYTES = 5 * 1024 * 1024


async def read_capped_body(
    response: httpx.Response, *, max_bytes: int = MAX_RESPONSE_BYTES
) -> tuple[bytes, bool]:
    """Read a streamed response body, stopping at ``max_bytes``.

    Returns ``(body, truncated)``. The response stream is always closed and the
    caller receives at most ``max_bytes`` of decoded body — regardless of what
    the server declares (or omits) in ``Content-Length``. ``truncated`` is True
    when any bytes were dropped, so the caller can flag the result instead of
    silently extracting from a partial document.
    """
    declared = response.headers.get("content-length", "")
    truncated = declared.isdigit() and int(declared) > max_bytes
    chunks: list[bytes] = []
    total = 0
    try:
        async for chunk in response.aiter_bytes():
            room = max_bytes - total
            if len(chunk) > room:
                chunks.append(chunk[:room])
                total = max_bytes
                truncated = True
                break
            chunks.append(chunk)
            total += len(chunk)
    finally:
        await response.aclose()
    return b"".join(chunks), truncated


# Pinning: the validated IP is the CONNECT target, so httpx cannot re-resolve
# the name (TOCTOU / DNS rebinding). Requires httpx >= 0.27 (httpcore >= 1.0),
# where request extensions carry ``sni_hostname``: TLS still verifies the
# original hostname and Host preserves virtual-host routing.


async def safe_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_redirects: int = 10,
    **kwargs: Any,
) -> httpx.Response:
    """GET with SSRF-safe redirect re-validation and pinned-IP connects.

    Every redirect hop is re-validated (including DNS) before the request;
    private/loopback/link-local targets abort the chain. Pinning needs
    httpx >= 0.27 and a client with follow_redirects=False (default).

    A client with ``follow_redirects=True`` is refused: httpx would follow the
    redirect itself, before this loop can validate the hop, and the
    metadata/link-local target would be reached.
    """
    from pry.engine.url_pinning import pinned_get

    if getattr(client, "follow_redirects", False) is True:
        raise ValueError(
            "safe_get requires an httpx client with follow_redirects=False "
            "(httpx would follow redirects unvalidated)"
        )

    current = url
    # Explicit pre-flight validation for the first hop; pinned_get re-validates
    # at connect time (TOCTOU/DNS-rebinding), this makes the contract local.
    validate_redirect_url(current)
    response = await pinned_get(client, current, {**kwargs, "stream": True})
    redirects = 0
    while response.is_redirect and redirects < max_redirects:
        location = response.headers.get("location")
        if not location:
            break
        # Join on the logical URL, not the pinned-IP request URL, then validate
        # this hop BEFORE any second request is issued.
        current = urljoin(current, location)
        validate_redirect_url(current)
        await response.aclose()
        response = await pinned_get(client, current, {**kwargs, "stream": True})
        redirects += 1
    body, truncated = await read_capped_body(response)
    # Hand the body back in the streamed response so every caller's
    # ``response.text`` / ``.json()`` keeps working unchanged.
    response._content = body
    response.extensions["pry_truncated"] = truncated
    if truncated:
        logger.warning(
            "response_body_truncated",
            extra={"url": current, "limit_bytes": MAX_RESPONSE_BYTES},
        )
    return response


__all__ = ["MAX_RESPONSE_BYTES", "read_capped_body", "safe_get"]
