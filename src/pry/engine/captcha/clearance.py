"""Pry — the ``cf_clearance`` cache: one cookie pair per domain, replayed.

FlareSolverr clears a Cloudflare challenge once and returns a ``cf_clearance``
cookie plus the UA that earned it. Re-solving on every fetch is what makes a
client look like a bot, so the pair is stored per hostname and replayed instead.

Backends (``PRY_CAPTCHA_CLEARANCE_BACKEND``): ``memory`` (default, process
local) or ``redis`` (shared, ``redis.asyncio`` — no new dependency); a Redis
failure degrades to memory and never fails a fetch. TTL:
``PRY_CAPTCHA_CLEARANCE_TTL_S``, default 1800 s (Cloudflare's default).

Binding: valid only for the UA that obtained it and, in practice, the egress
IP. The UA is stored with the cookie and ``get(domain, user_agent=...)``
rejects a mismatch, so a UA change or IP rotation kills the entry; the next
fetch sees a challenge, the ladder re-solves, a fresh pair replaces it. Never
rewrite a stored UA — that cookie cannot work. Keying: the exact lowercased
hostname; two hostnames carrying the *same* cookie value keep separate
entries, so invalidating one never touches the other.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from functools import cache
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

ENABLED_ENV = "PRY_CAPTCHA_CLEARANCE_ENABLED"
BACKEND_ENV = "PRY_CAPTCHA_CLEARANCE_BACKEND"
TTL_ENV = "PRY_CAPTCHA_CLEARANCE_TTL_S"
REDIS_URL_ENV = "PRY_CAPTCHA_CLEARANCE_REDIS_URL"
DEFAULT_TTL_S = 1800.0
_MISS = object()
Cookies = Mapping[str, str] | Iterable[Mapping[str, object]]


def domain_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def enabled() -> bool:
    return os.environ.get(ENABLED_ENV, "").strip().lower() not in {"0", "false", "no", "off"}


try:  # Redis is a declared dependency; a stub install still degrades to memory.
    from redis.exceptions import RedisError as _RedisError
except ImportError:  # pragma: no cover
    logger.debug("best-effort fallback", exc_info=True)
    _RedisError = OSError


def _cf_clearance(cookies: Cookies) -> str:
    """Pull ``cf_clearance`` out of a mapping or FlareSolverr's cookie list."""
    if isinstance(cookies, Mapping):
        return str(cookies.get("cf_clearance") or "")
    for item in cookies or ():
        if isinstance(item, Mapping) and item.get("name") == "cf_clearance":
            return str(item.get("value") or "")
    return ""


@dataclass(frozen=True, slots=True)
class Clearance:
    """One domain's clearance: cookie, the UA that earned it, and its age."""

    cf_clearance: str
    user_agent: str
    obtained_at: float
    ttl_s: float
    source_tier: str

    def cookie_header(self) -> str:
        return f"cf_clearance={self.cf_clearance}"

    @classmethod
    def from_dict(cls, raw: object) -> Clearance | None:
        if not isinstance(raw, Mapping):
            return None
        try:
            return cls(
                str(raw["cf_clearance"]),
                str(raw["user_agent"]),
                float(raw["obtained_at"]),
                float(raw["ttl_s"]),
                str(raw["source_tier"]),
            )
        except (KeyError, TypeError, ValueError):
            logger.debug("best-effort fallback", exc_info=True)
            return None


class ClearanceStore:
    """Domain-keyed clearances with TTL, UA binding, and a memory/Redis tier."""

    def __init__(
        self,
        backend: str = "memory",
        ttl_s: float = DEFAULT_TTL_S,
        redis_url: str = "",
        client: object | None = None,
    ) -> None:
        self.backend, self.ttl_s, self.redis_url = backend, ttl_s, redis_url
        self._client = client
        self._memory: dict[str, Clearance] = {}

    async def get(self, domain: str, user_agent: str | None = None) -> Clearance | None:
        item = await self._load(domain)
        if item is not None and time.time() >= item.obtained_at + item.ttl_s:
            await self.invalidate(domain)
            item = None
        if item is not None and user_agent is not None and user_agent != item.user_agent:
            item = None
        return item

    async def put(
        self, domain: str, cookies: Cookies, user_agent: str, source_tier: str
    ) -> Clearance | None:
        value = _cf_clearance(cookies)
        if not domain or not value or not user_agent:
            return None
        item = Clearance(value, user_agent, time.time(), self.ttl_s, source_tier)
        self._memory[domain] = item
        if self.backend == "redis":
            await self._redis_op("set", domain, item)
        return item

    async def invalidate(self, domain: str) -> None:
        self._memory.pop(domain, None)
        if self.backend == "redis":
            await self._redis_op("del", domain)

    async def _load(self, domain: str) -> Clearance | None:
        if self.backend == "redis":
            raw = await self._redis_op("get", domain)
            if raw is not _MISS and raw is not None:
                try:
                    item = Clearance.from_dict(json.loads(raw))
                except ValueError:
                    logger.debug("best-effort fallback", exc_info=True)
                    item = None
                if item is not None:
                    return item
        return self._memory.get(domain)

    def _redis(self) -> object:
        if self._client is None:
            from redis.asyncio import Redis

            url = os.environ.get(REDIS_URL_ENV) or os.environ.get("PRY_REDIS_URL", "")
            self._client = Redis.from_url(self.redis_url or url, decode_responses=True)
        return self._client

    async def _redis_op(self, op: str, domain: str, item: Clearance | None = None) -> object:
        key = f"pry:clearance:{domain}"
        try:
            client = self._redis()
            if op == "get":
                return await client.get(key)  # type: ignore[attr-defined]
            if op == "del":
                return await client.delete(key)  # type: ignore[attr-defined]
            assert item is not None
            return await client.setex(  # type: ignore[attr-defined]
                key, max(int(item.ttl_s), 1), json.dumps(asdict(item))
            )
        except (_RedisError, OSError) as exc:
            logger.warning("clearance_redis_unavailable op=%s error=%s", op, type(exc).__name__)
            return _MISS


@cache
def store() -> ClearanceStore:
    """The process-wide store, built once from the environment."""
    try:
        ttl = float(os.environ.get(TTL_ENV, ""))
    except ValueError:
        logger.debug("best-effort fallback", exc_info=True)
        ttl = DEFAULT_TTL_S
    backend = os.environ.get(BACKEND_ENV, "memory").strip().lower()
    return ClearanceStore(
        backend if backend in ("memory", "redis") else "memory",
        ttl if ttl > 0 else DEFAULT_TTL_S,
    )


async def record(url: str, token: str, source_tier: str) -> Clearance | None:
    """Parse a solver token (cookies + UA) and store it for ``url``'s domain."""
    if not enabled() or not token:
        return None
    try:
        data = json.loads(token)
    except (TypeError, ValueError):
        logger.debug("best-effort fallback", exc_info=True)
        return None
    if not isinstance(data, Mapping):
        return None
    cookies, ua = data.get("cookies") or [], str(data.get("userAgent") or "")
    return await store().put(domain_of(url), cookies, ua, source_tier)
