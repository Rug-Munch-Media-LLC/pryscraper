"""Pry — ordered fetch lanes: direct, residential, FlareSolverr, Tor.

Engines block by exit-IP class, so ``fetch`` walks an ordered ladder inside one
deadline and stops at the first success. Captcha / rate-limit refusals describe
the exit node and escalate (a bare 403 does too); ``blocked.robots`` describes
the URL and is terminal.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlsplit

import httpx

from pry.core.errors import PryError
from pry.engine.url_guard import safe_get

logger = logging.getLogger(__name__)

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
_LOCK = threading.Lock()
_LAST: dict[str, dict[str, Any]] = {}  # host -> last outcome, per-engine reporting


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

    async def get(self, url: str, timeout_s: float) -> Reply:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(max(0.05, timeout_s)),
            follow_redirects=False,
            proxy=self._proxy,
            headers={"User-Agent": UA, "Accept": "*/*"},
        )
        async with client:
            resp = await safe_get(client, url)  # SSRF guard on every hop
            body = (resp.text or "")[:MAX_BODY]
            return Reply(classify(resp.status_code, body), resp.status_code, body)


class Proxied(Direct):
    """Direct over a proxy endpoint: Webshare rotation or local Tor SOCKS5."""

    def __init__(self, name: str, proxy_of: Any) -> None:
        super().__init__()
        self.name, self._proxy_of = name, proxy_of

    async def get(self, url: str, timeout_s: float) -> Reply:
        self._proxy = self._proxy_of()
        if not self._proxy:
            raise LaneUnavailable(f"{self.name} has no proxy endpoint")
        try:
            return await Direct.get(self, url, timeout_s)
        except ImportError as exc:  # httpx[socks] is not installed
            raise LaneUnavailable(f"{self.name}: missing socks transport") from exc


class FlareSolverr:
    """A real browser via FlareSolverr (host-mapped to 127.0.0.1:8192)."""

    name = "flaresolverr"

    def __init__(self, endpoint: str | None = None) -> None:
        self._endpoint = endpoint or os.getenv(
            "PRY_FLARESOLVERR_HOST_URL", "http://127.0.0.1:8192/v1"
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


def _webshare_proxy() -> str | None:
    """Rotating residential endpoint; None while the pool is unprovisioned."""
    from pry.engine.webshare_proxy import next_webshare_proxy

    return next_webshare_proxy()


def build_lanes() -> dict[str, FetchLane]:
    """The default ladder, built per call so env changes are honoured."""
    tor = os.getenv("PRY_TOR_SOCKS", "socks5h://127.0.0.1:9050")
    return {
        "direct": Direct(),
        "webshare": Proxied("webshare", _webshare_proxy),
        "flaresolverr": FlareSolverr(),
        "tor": Proxied("tor", lambda: tor),
    }


def lane_table(hosts: dict[str, str]) -> dict[str, dict[str, Any]]:
    """Last lane outcome per engine name, keyed by the host that engine called."""
    with _LOCK:
        return {
            eng: dict(_LAST.get(h.lower(), {"lane_used": None, "lanes_tried": []}))
            for eng, h in hosts.items()
        }


async def fetch(
    url: str, *, lanes: tuple[str, ...] = LANE_NAMES, timeout_ms: int = 8000, resolver: Any = None
) -> dict[str, Any]:
    """Try ``lanes`` in order inside ``timeout_ms``; ``resolver`` is the DI seam."""
    deadline = time.perf_counter() + max(1, int(timeout_ms)) / 1000.0
    table = build_lanes()
    pick = resolver if callable(resolver) else (resolver or table).get
    attempts: list[dict[str, Any]] = []
    status, code, body, used = TIMEOUT, 0, "", None
    for name in lanes:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            status, code, body = TIMEOUT, 0, ""
            break
        started = time.perf_counter()
        try:
            lane = pick(name)
            if lane is None:
                raise LaneUnavailable(f"unknown lane {name}")
            reply = await asyncio.wait_for(lane.get(url, remaining), remaining)
            status, code, body = reply.status, reply.code, reply.body
        except TimeoutError:
            status, code, body = TIMEOUT, 0, ""
        except LaneUnavailable as exc:
            logger.debug("fetch_lane_unavailable", extra={"lane": name, "error": str(exc)[:120]})
            status, code, body = UNAVAILABLE, 0, ""
        except (httpx.HTTPError, OSError, RuntimeError, ValueError, PryError) as exc:
            logger.debug("fetch_lane_failed", extra={"lane": name, "error": str(exc)[:120]})
            status, code, body = ERROR, 0, ""
        attempts.append(
            {
                "lane": name,
                "status": status,
                "code": code,
                "ms": int((time.perf_counter() - started) * 1000),
            }
        )
        if status == OK:
            used = name
            break
        if status in TERMINAL:
            break
    with _LOCK:
        _LAST[(urlsplit(url).hostname or "").lower()] = {
            "lane_used": used,
            "lanes_tried": [a["lane"] for a in attempts],
            "status": status,
        }
    return {"status": status, "lane_used": used, "attempts": attempts, "body": body if used else ""}
