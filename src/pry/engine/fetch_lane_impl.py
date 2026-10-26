"""Pry — concrete fetch lanes: direct, proxied (Webshare/Tor), FlareSolverr.

A refusal describes either the exit node (captcha / rate limit / bare 403) or
the URL (``robots``). Only the former escalates, so lane classes report the
vocabulary and let :mod:`pry.engine.fetch_lanes` decide.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlsplit

import httpx

from pry.engine.url_guard import safe_get

LANE_NAMES: tuple[str, ...] = ("direct", "webshare", "flaresolverr", "tor")
OK, ERROR, UNAVAILABLE = "ok", "error", "unavailable"
ROBOTS, CAPTCHA = "blocked.robots", "blocked.captcha"
RATE_LIMIT, TIMEOUT = "blocked.rate_limit", "blocked.timeout"
TERMINAL = frozenset({ROBOTS})  # about the URL, not the exit node: never escalate
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36"
MAX_BODY = 2_000_000
_CAPTCHA_MARKS = (
    "captcha",
    "cf-challenge",
    "unusual traffic",
    "are you a robot",
    "verify you are human",
    "just a moment",
)
_ROBOTS_MARKS = ("robots.txt", "blocked by robots", "disallowed by robots")


@dataclass(slots=True)
class Reply:
    status: str
    code: int
    body: str = ""


class LaneUnavailable(RuntimeError):
    """No transport configured (empty proxy pool, missing socksio)."""


@runtime_checkable
class FetchLane(Protocol):
    """A transport able to produce a :class:`Reply` for one URL."""

    name: str

    async def get(self, url: str, timeout_s: float) -> Reply: ...


def classify(code: int, body: str = "") -> str:
    """Map an HTTP answer onto the refusal vocabulary (code 0 = no answer)."""
    low = (body or "")[:20000].lower()
    if code == 0:
        return TIMEOUT
    if any(mark in low for mark in _ROBOTS_MARKS):
        return ROBOTS
    if any(mark in low for mark in _CAPTCHA_MARKS):
        return CAPTCHA
    if code in (403, 429, 503):
        return RATE_LIMIT
    return OK if 200 <= code < 300 else ERROR


class Direct:
    """Plain egress from this host."""

    name = "direct"

    def __init__(self, proxy: str | None = None) -> None:
        self._proxy = proxy

    def _client(self, timeout_s: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(max(0.05, timeout_s)),
            follow_redirects=False,
            proxy=self._proxy,
            headers={"User-Agent": UA, "Accept": "*/*"},
        )

    @staticmethod
    def _reply(resp: httpx.Response) -> Reply:
        body = (resp.text or "")[:MAX_BODY]
        return Reply(classify(resp.status_code, body), resp.status_code, body)

    async def get(self, url: str, timeout_s: float) -> Reply:
        async with self._client(timeout_s) as client:
            resp = await safe_get(client, url)  # SSRF guard + DNS pinning per hop
        return self._reply(resp)


def _host_of(proxy: str) -> str:
    return urlsplit(proxy).hostname or ""


class Proxied(Direct):
    """Direct over a proxy endpoint: Webshare pool rotation or local Tor SOCKS5.

    ``on_bad`` receives a failing endpoint's host so the pool can cool it down;
    the refusal is still returned/raised so the ladder escalates exactly once.
    """

    def __init__(self, name: str, proxy_of: Any, on_bad: Any = None) -> None:
        super().__init__()
        self.name, self._proxy_of, self._on_bad = name, proxy_of, on_bad

    async def get(self, url: str, timeout_s: float) -> Reply:
        from pry.engine.url_guard import validate_url

        self._proxy = self._proxy_of(timeout_s)
        if not self._proxy:
            raise LaneUnavailable(f"{self.name} has no proxy endpoint")
        validate_url(url, resolve_dns=False)  # SSRF policy only: the exit node resolves
        try:
            async with self._client(timeout_s) as client:
                reply = self._reply(await client.get(url))
        except ImportError as exc:  # httpx[socks] is not installed
            raise LaneUnavailable(f"{self.name}: missing socks transport") from exc
        except (httpx.HTTPError, OSError) as exc:
            self._mark_bad()
            raise LaneUnavailable(f"{self.name} endpoint failed: {type(exc).__name__}") from exc
        if reply.status in (CAPTCHA, RATE_LIMIT, TIMEOUT):
            self._mark_bad()
        return reply

    def _mark_bad(self) -> None:
        if self._on_bad and self._proxy:
            self._on_bad(_host_of(self._proxy))


class FlareSolverr:
    """A real browser via FlareSolverr (canonical flaresolverr:8191)."""

    name = "flaresolverr"

    def __init__(self, endpoint: str | None = None) -> None:
        self._endpoint = endpoint or os.getenv(
            "PRY_FLARESOLVERR_HOST_URL", "http://flaresolverr:8191/v1"
        )

    async def get(self, url: str, timeout_s: float) -> Reply:
        async with httpx.AsyncClient(timeout=httpx.Timeout(max(1.0, timeout_s))) as c:
            resp = await c.post(
                self._endpoint,
                json={
                    "cmd": "request.get",
                    "url": url,
                    "maxTimeout": int(max(1.0, timeout_s) * 1000),
                },
            )
        solution = (resp.json() or {}).get("solution") or {}  # non-JSON -> ERROR
        if not solution:
            return Reply(ERROR, resp.status_code)
        code = int(solution.get("status") or 0)
        body = str(solution.get("response") or "")[:MAX_BODY]
        return Reply(classify(code, body), code, body)


def webshare_proxy(budget_s: float | None = None) -> str | None:
    """Endpoint from the cached Webshare API pool; None while unavailable."""
    from pry.engine.webshare_pool import next_proxy

    return next_proxy(budget_s)


def webshare_bad(host: str) -> None:
    """Cool a failing Webshare endpoint down (best-effort, never raises)."""
    if not host:
        return
    from pry.engine.webshare_pool import mark_bad

    mark_bad(host)
