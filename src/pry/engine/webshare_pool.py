"""Pry — cached Webshare residential proxy pool (API-backed).

Deployments hold only ``WEBSHARE_API_KEY``, so the env/gopass list loader in
:mod:`pry.engine.webshare_proxy` resolves nothing. Here we fetch the proxy list
once per TTL, persist it, and hand out ``http://user:pass@host:port`` URLs while
cooling down endpoints that fail. A tight caller budget is never exceeded.

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
import os
import threading
import time
from urllib.parse import quote

import httpx

from pry.engine import webshare_cache as cache
from pry.engine.webshare_api import api_key, fetch_proxies

logger = logging.getLogger(__name__)

TTL_S = float(os.getenv("PRY_WEBSHARE_TTL_S", "3600"))
BAD_TTL_S = float(os.getenv("PRY_WEBSHARE_BAD_TTL_S", "900"))
HTTP_TIMEOUT_S = 5.0

_LOCK = threading.Lock()
_STATE: dict = {"proxies": [], "fetched_at": 0.0, "bad": {}, "index": 0, "loaded": False}


def _snapshot() -> dict:
    return {"fetched_at": _STATE["fetched_at"], "proxies": _STATE["proxies"], "bad": _STATE["bad"]}


def _load() -> None:
    data = cache.load()
    _STATE["proxies"] = list(data.get("proxies") or [])
    _STATE["fetched_at"] = float(data.get("fetched_at") or 0.0)
    now = time.time()
    _STATE["bad"] = {h: float(t) for h, t in (data.get("bad") or {}).items() if float(t) > now}
    _STATE["loaded"] = True


def _refresh(budget_s: float | None) -> bool:
    key = api_key()
    timeout_s = HTTP_TIMEOUT_S if budget_s is None else max(0.5, min(HTTP_TIMEOUT_S, budget_s))
    if not key:
        logger.debug("webshare_key_missing")
        return False
    try:
        rows = fetch_proxies(key, timeout_s)
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        logger.warning("webshare_pool_refresh_failed", extra={"error": type(exc).__name__})
        return False
    _STATE["proxies"] = [
        {
            "host": str(r["proxy_address"]),
            "port": int(r["port"]),
            "user": str(r.get("username") or ""),
            "password": str(r.get("password") or ""),
        }
        for r in rows
    ]
    _STATE["fetched_at"] = time.time()
    cache.save(_snapshot())
    logger.info("webshare_pool_refreshed", extra={"count": len(_STATE["proxies"])})
    return bool(_STATE["proxies"])


def _ensure(budget_s: float | None = None) -> None:
    with _LOCK:
        if not _STATE["loaded"]:
            _load()
        fresh = _STATE["proxies"] and (time.time() - float(_STATE["fetched_at"])) < TTL_S
        tight = budget_s is not None and budget_s < 1.0 and _STATE["proxies"]
        if fresh or tight:
            return  # fresh, or a stale endpoint beats blowing the caller's deadline
        _refresh(budget_s)


def pool_size(budget_s: float | None = None) -> int:
    """Cached endpoint count (refreshing when the TTL has lapsed)."""
    _ensure(budget_s)
    return len(_STATE["proxies"])


def next_proxy(budget_s: float | None = None) -> str | None:
    """Round-robin over live endpoints; None when the pool is empty."""
    _ensure(budget_s)
    with _LOCK:
        now = time.time()
        live = [p for p in _STATE["proxies"] if _STATE["bad"].get(p["host"], 0.0) <= now]
        if not live:
            return None
        pick = live[_STATE["index"] % len(live)]
        _STATE["index"] += 1
    auth = (
        f"{quote(pick['user'], safe='')}:{quote(pick['password'], safe='')}@"
        if pick["user"]
        else ""
    )
    return f"http://{auth}{pick['host']}:{pick['port']}"


def mark_bad(host: str, ttl_s: float = BAD_TTL_S) -> None:
    """Skip ``host`` for ``ttl_s`` seconds (default 15 min)."""
    with _LOCK:
        _STATE["bad"][host] = time.time() + max(1.0, float(ttl_s))
        cache.save(_snapshot())
    logger.info("webshare_proxy_bad", extra={"host": f"{host.rsplit('.', 1)[0]}.*", "ttl_s": ttl_s})


def reset_cache() -> None:
    """Forget in-memory state (tests / config reload)."""
    with _LOCK:
        _STATE.update({"proxies": [], "fetched_at": 0.0, "bad": {}, "index": 0, "loaded": False})
