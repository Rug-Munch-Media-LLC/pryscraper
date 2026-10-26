"""Pry — T0: the clean profile (no solving at all).

The cheapest rung is not solving: present a browser-consistent profile
(curl_cffi TLS/JA3 + header order) and hope the challenge never appears. It is
always attempted first and answers ``unsolved`` when the page still carries a
challenge, which escalates to T1.

``curl_cffi`` is optional: absent -> ``capability()`` is False and the ladder
skips the rung with ``unavailable.model``.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from pry.engine.captcha.flaresolverr import looks_unsolved

IMPERSONATE = "chrome131"
DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}


def capability() -> bool:
    """True when curl_cffi (impersonating TLS) is importable."""
    try:
        import curl_cffi  # noqa: F401
    except ImportError:
        return False
    return True


async def fetch_clean(url: str, timeout_s: float = 20.0) -> tuple[str | None, str]:
    """Fetch ``url`` with a clean profile -> (html, reason).

    ``reason`` is ``solved`` when the response carries no challenge marker,
    otherwise ``unsolved`` (or ``failed`` on a transport error).
    """
    if not capability():
        return None, "unavailable.model"
    from curl_cffi.requests import AsyncSession

    try:
        async with AsyncSession(impersonate=IMPERSONATE, timeout=timeout_s) as session:
            resp = await session.get(url, headers=DEFAULT_HEADERS)
    except (OSError, RuntimeError, ValueError):
        return None, "failed"
    html = resp.text or ""
    if not html:
        return None, "unsolved"
    return (html, "unsolved") if looks_unsolved(html) else (html, "solved")
