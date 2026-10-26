"""Pry — ordered fetch lanes: direct, residential, FlareSolverr, Tor.

Engines block by exit-IP class, so ``fetch`` walks an ordered ladder inside one
deadline and stops at the first success. Captcha / rate-limit refusals describe
the exit node and escalate (a bare 403 does too); ``blocked.robots`` describes
the URL and is terminal on every lane.

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
from typing import Any
from urllib.parse import urlsplit

import httpx

from pry.core.errors import PryError
from pry.engine.fetch_lane_impl import (
    CAPTCHA,
    ERROR,
    LANE_NAMES,
    OK,
    RATE_LIMIT,
    ROBOTS,
    TERMINAL,
    TIMEOUT,
    UNAVAILABLE,
    Direct,
    FetchLane,
    FlareSolverr,
    LaneUnavailable,
    Proxied,
    Reply,
    classify,
    webshare_bad,
    webshare_proxy,
)

logger = logging.getLogger(__name__)

__all__ = [
    "CAPTCHA",
    "ERROR",
    "LANE_NAMES",
    "OK",
    "RATE_LIMIT",
    "ROBOTS",
    "TERMINAL",
    "TIMEOUT",
    "UNAVAILABLE",
    "Direct",
    "FetchLane",
    "FlareSolverr",
    "LaneUnavailable",
    "Proxied",
    "Reply",
    "build_lanes",
    "classify",
    "fetch",
    "lane_table",
]

_LOCK = threading.Lock()
_LAST: dict[str, dict[str, Any]] = {}  # host -> last outcome, per-engine reporting


def _webshare_proxy(budget_s: float | None = None) -> str | None:
    """Rotating Webshare endpoint from the API pool; None while unprovisioned."""
    return webshare_proxy(budget_s)


def build_lanes() -> dict[str, FetchLane]:
    """The default ladder, built per call so env changes are honoured."""
    tor = os.getenv("PRY_TOR_SOCKS", "socks5h://127.0.0.1:9050")
    return {
        "direct": Direct(),
        "webshare": Proxied("webshare", _webshare_proxy, on_bad=webshare_bad),
        "flaresolverr": FlareSolverr(),
        "tor": Proxied("tor", lambda _budget=None: tor),
    }


def lane_table(hosts: dict[str, str]) -> dict[str, dict[str, Any]]:
    """Last lane outcome per engine name, keyed by the host that engine called."""
    with _LOCK:
        return {
            eng: dict(_LAST.get(h.lower(), {"lane_used": None, "lanes_tried": []}))
            for eng, h in hosts.items()
        }


async def _one(pick: Any, name: str, url: str, remaining: float) -> tuple[str, int, str]:
    """One lane attempt -> (status, code, body); never raises, never retries."""
    try:
        lane = pick(name)
    except (KeyError, TypeError, AttributeError):
        lane = None
    if lane is None:
        logger.debug("fetch_lane_unavailable", extra={"lane": name, "error": "unknown lane"})
        return UNAVAILABLE, 0, ""
    try:
        reply = await asyncio.wait_for(lane.get(url, remaining), remaining)
        return reply.status, reply.code, reply.body
    except TimeoutError:
        return TIMEOUT, 0, ""
    except LaneUnavailable as exc:
        logger.debug("fetch_lane_unavailable", extra={"lane": name, "error": str(exc)[:120]})
        return UNAVAILABLE, 0, ""
    except (httpx.HTTPError, OSError, RuntimeError, ValueError, PryError) as exc:
        logger.debug("fetch_lane_failed", extra={"lane": name, "error": str(exc)[:120]})
        return ERROR, 0, ""


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
        status, code, body = await _one(pick, name, url, remaining)
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
