"""Shared response-body caps for every transport tier.

``MAX_RESPONSE_BYTES`` is owned by :mod:`pry.engine.url_guard` (the SSRF-safe
``safe_get`` path). This module re-exports it so cloudscraper, FlareSolverr,
Camoufox and Tor all cap at the same number instead of redefining 5 MiB.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pry.engine.url_guard import MAX_RESPONSE_BYTES, read_capped_body

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)

#: A FlareSolverr reply wraps the page in JSON. Escaping can inflate the page
#: several times over, so the envelope is streamed with a larger (still bounded)
#: ceiling and the embedded ``solution.response`` string is then capped at
#: ``MAX_RESPONSE_BYTES``.
MAX_JSON_ENVELOPE_BYTES = 4 * MAX_RESPONSE_BYTES

__all__ = [
    "MAX_JSON_ENVELOPE_BYTES",
    "MAX_RESPONSE_BYTES",
    "cap_bytes",
    "cap_httpx_stream",
    "cap_text",
]


def _log_truncated(url: str, limit: int) -> None:
    logger.warning("response_body_truncated", extra={"url": url, "limit_bytes": limit})


def cap_bytes(
    data: bytes, url: str = "", *, max_bytes: int = MAX_RESPONSE_BYTES
) -> tuple[bytes, bool]:
    """Cut ``data`` at ``max_bytes``.

    Returns ``(capped, truncated)``. ``truncated`` is True when any byte was
    dropped, so the caller can flag a partial document instead of silently
    extracting from it.
    """
    if len(data) <= max_bytes:
        return data, False
    _log_truncated(url, max_bytes)
    return data[:max_bytes], True


def cap_text(text: str, url: str = "", *, max_bytes: int = MAX_RESPONSE_BYTES) -> tuple[str, bool]:
    """String counterpart of :func:`cap_bytes` (chars, not encoded bytes)."""
    if len(text) <= max_bytes:
        return text, False
    _log_truncated(url, max_bytes)
    return text[:max_bytes], True


async def cap_httpx_stream(
    response: httpx.Response, *, max_bytes: int = MAX_RESPONSE_BYTES
) -> tuple[bytes, bool]:
    """Drain an httpx response stream, stopping at ``max_bytes``.

    Always closes the stream. Used by the FlareSolverr tiers so a multi-GB
    JSON envelope is never materialised before the cap is applied.
    """
    request = getattr(response, "request", None)
    url = str(getattr(request, "url", "")) if request is not None else ""
    body, truncated = await read_capped_body(response, max_bytes=max_bytes)
    if truncated:
        _log_truncated(url, max_bytes)
    return body, truncated
