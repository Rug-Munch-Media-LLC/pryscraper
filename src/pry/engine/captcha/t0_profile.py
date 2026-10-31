"""Pry — T0: the clean profile (no solving at all).

The cheapest rung is not solving: present a browser-consistent profile and hope
the challenge never appears. Measured on 2026-10-26 (see the PR body), the
hand-written header dict that used to live here *caused* 403s on DataDome
properties (leboncoin, etsy): it replaced Chrome's ``Accept`` with a shorter
one and dropped ``sec-ch-ua`` / ``priority``, leaving a Chrome user-agent whose
client hints disagreed with it. curl_cffi already emits the profile's headers
in browser order, so T0 now sends none of its own and lets the impersonation
target own user-agent, client hints and header order.

Wire behaviour:

* ``PROFILE`` is the moving ``chrome`` alias, not a pinned build: pinning
  ``chrome131`` ages into a fingerprint no browser has any more.
* HTTP/2 is negotiated by the impersonation profile (verified: ``ja4``
  ``t13d1516h2_…`` and an h2 HEADERS frame).
* Redirects are followed (max 5) so a ``302`` + ``Set-Cookie`` clearance is
  actually consumed instead of being reported as an unsolved page.
* Cookies live in one jar per host for the life of the process, so a clearance
  cookie issued while fetching page A is sent when fetching page B.
* Exactly one request per call. A 403/503, a challenge marker or an empty body
  is ``unsolved`` with the reason — never a retry loop; the ladder above owns
  escalation.

``curl_cffi`` is optional: absent -> :func:`capability` is False and the ladder
skips the rung with ``unavailable.model``.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from pry.engine.captcha.flaresolverr import looks_unsolved

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from curl_cffi.requests import Cookies

#: Moving alias -> curl_cffi's newest Chrome fingerprint. Do not pin a build.
PROFILE = "chrome"
TIMEOUT_S = 20.0
MAX_REDIRECTS = 5

#: One cookie jar per host, kept for the process lifetime.
jars: dict[str, Cookies] = {}


@dataclass(slots=True)
class Reply:
    """The parts of a response T0 is allowed to look at."""

    status: int
    text: str
    cookies: Cookies


def capability() -> bool:
    """True when curl_cffi (impersonating TLS) is importable."""
    try:
        import curl_cffi  # noqa: F401
    except ImportError:
        logger.debug("best-effort fallback", exc_info=True)
        return False
    return True


def domain_of(url: str) -> str:
    """Lower-case host of ``url``; the cookie jar key."""
    return (urlsplit(url).hostname or "").lower()


def base_headers() -> dict[str, str]:
    """Headers T0 adds on top of the profile — deliberately none.

    The impersonation target owns user-agent, ``sec-ch-ua``, ``Accept``,
    ``Accept-Language``, ``sec-fetch-*`` and their order. Overriding any of
    them is how a request stops looking like the browser it claims to be.
    """
    return {}


def classify(status: int, html: str) -> str:
    """``solved`` only for a clean 200; otherwise the unsolved reason."""
    if status != 200:
        return f"unsolved.http_{status}"
    if not (html or "").strip():
        return "unsolved.empty"
    return "unsolved.marker" if looks_unsolved(html) else "solved"


def jar_for(url: str) -> Cookies:
    """Cookie jar for ``url``'s host, created on first use."""
    from curl_cffi.requests import Cookies

    return jars.setdefault(domain_of(url), Cookies())


def _merge(target: Cookies, fresh: Cookies) -> None:
    """Copy cookies the response set into the process-wide jar."""
    seen = {(c.domain, c.path, c.name) for c in target.jar}
    for cookie in fresh.jar:
        if (cookie.domain, cookie.path, cookie.name) not in seen:
            target.jar.set_cookie(cookie)


async def _http_get(url: str, timeout_s: float, cookies: Cookies) -> Reply:
    """One request with the profile's headers and ``cookies`` as the jar."""
    from curl_cffi.requests import AsyncSession

    async with AsyncSession(
        impersonate=PROFILE,
        timeout=timeout_s,
        cookies=cookies,
        allow_redirects=True,
        max_redirects=MAX_REDIRECTS,
    ) as session:
        resp = await session.get(url, headers=base_headers())
        return Reply(status=int(resp.status_code), text=resp.text or "", cookies=session.cookies)


async def fetch_clean(url: str, timeout_s: float = TIMEOUT_S) -> tuple[str | None, str]:
    """Fetch ``url`` with the T0 profile -> (html, reason).

    ``reason`` is ``solved`` only when a 200 arrives with no challenge marker;
    every other outcome names why T0 gave up, so the ladder can escalate.
    """
    if not capability():
        return None, "unavailable.model"
    jar = jar_for(url)
    try:
        reply = await _http_get(url, timeout_s, jar)
    except (OSError, RuntimeError, ValueError):
        logger.debug("best-effort fallback", exc_info=True)
        return None, "failed"
    _merge(jar, reply.cookies)
    reason = classify(reply.status, reply.text)
    return (None, reason) if reason != "solved" else (reply.text, reason)
