"""Pry — FlareSolverr lane (free, no API key required).

FlareSolverr drives a real browser through JS / Cloudflare interstitials and
returns the settled HTML plus the cookies and User-Agent that cleared the
challenge. The lane counts as solved only when the returned HTML no longer
carries challenge markers — a 200 that still says "verify you are human" is a
failure, not a solve.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

import httpx

from pry.core.settings import settings
from pry.engine.captcha.base import CaptchaProvider
from pry.engine.captcha.registry import register

logger = logging.getLogger(__name__)

# 8192 is the host-published port (host-run dev only); 8191 on loopback
# would be pry itself inside the API container, so it is not a fallback.
# Host-published port; inside the API container 8192 is pry itself, so this is
# opt-in only (PRY_FLARESOLVERR_ALLOW_LOOPBACK=1) and never a silent fallback.
LOOPBACK_FALLBACKS = ("http://127.0.0.1:8192/v1",)
CLEARANCE_COOKIES = ("cf_clearance",)
UNSOLVED_MARKERS = (
    "g-recaptcha",
    "hcaptcha.com",
    "cf-turnstile",
    "just a moment",
    "checking your browser",
    "verify you are human",
    "attendere prego",
)


@dataclass(slots=True)
class FlareSolution:
    """Result of one FlareSolverr request."""

    ok: bool
    html: str = ""
    token: str = ""
    error: str = ""
    elapsed_ms: int = 0


def looks_unsolved(html: str) -> bool:
    """True when the HTML still contains a CAPTCHA/challenge marker."""
    lowered = (html or "").lower()
    return any(marker in lowered for marker in UNSOLVED_MARKERS)


def cleared_by(cookies: list | None) -> bool:
    """True when FlareSolverr returned a Cloudflare clearance cookie."""
    return any((c or {}).get("name") in CLEARANCE_COOKIES for c in (cookies or []))


def _endpoints() -> list[str]:
    """Configured FlareSolverr URL, plus loopback only when explicitly allowed."""
    ordered = [settings.flaresolverr_url]
    if os.environ.get("PRY_FLARESOLVERR_ALLOW_LOOPBACK") == "1":
        ordered += list(LOOPBACK_FALLBACKS)
    seen: list[str] = []
    for url in ordered:
        if url and url not in seen:
            seen.append(url)
    return seen


async def flaresolverr_fetch(url: str, timeout_s: float) -> FlareSolution:
    """Ask FlareSolverr to load ``url`` and return the settled solution."""
    import time

    started = time.monotonic()
    payload = {"cmd": "request.get", "url": url, "maxTimeout": int(max(timeout_s, 1) * 1000)}
    last_error = "no_endpoint"
    for endpoint in _endpoints():
        try:
            budget = max(timeout_s, 1)
            limits = httpx.Timeout(connect=2.0, read=budget + 5, write=5.0, pool=5.0)
            async with httpx.AsyncClient(timeout=limits) as client:
                resp = await client.post(endpoint, json=payload)
            resp.raise_for_status()
            data = resp.json()
            solution = data.get("solution") or {}
            html = solution.get("response") or ""
            if data.get("status") != "ok":
                last_error = str(data.get("message") or data.get("status") or "not_ok")
                continue
            cookies = solution.get("cookies") or []
            token = json.dumps({"cookies": cookies, "userAgent": solution.get("userAgent", "")})
            # A cleared Cloudflare page is a solve even when the site embeds a
            # recaptcha widget; markers only decide when no clearance cookie came back.
            solved = bool(html) and (cleared_by(cookies) or not looks_unsolved(html))
            return FlareSolution(
                ok=solved,
                html=html,
                token=token,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            last_error = type(exc).__name__
    return FlareSolution(
        ok=False, error=last_error, elapsed_ms=int((time.monotonic() - started) * 1000)
    )


class FlareSolverrProvider(CaptchaProvider):
    """Free JS/Cloudflare lane; returns cookies+UA as the resubmission token."""

    captcha_type = "flaresolverr"

    async def solve(self, *, url: str | None = None, **_: object) -> str | None:
        if not url:
            return None
        solution = await flaresolverr_fetch(url, float(settings.captcha_max_seconds))
        return solution.token if solution.ok else None


register(FlareSolverrProvider())
