"""Cold-key single-flight coalescing for the response cache.

Extracted from ``cache_redis`` so the lock map, the cross-replica ``SET NX PX``
guard and the poll-wait loop live in one small module instead of inflating the
backend mixin. ``cache`` is duck-typed: it must expose ``aget``/``aset``,
``_key``, ``_get_redis`` and ``_drop_redis``.

Guarantees, unchanged by the move:

* In-process: concurrent cold callers queue on a per-key ``asyncio.Lock``,
  re-check the cache inside it, and run ``loader`` once.
* Cross-replica: a Redis ``SET NX PX`` guard keeps one loader running while the
  others poll for its write.
* A lapsed PX TTL (holder crashed) makes a waiter load rather than block
  forever, so the worst case is a duplicate load, never a wedge.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from typing import Any

# Same namespace as the cache keys; short PX TTL so a crashed holder can never
# wedge a key — the guard lapses and the next caller loads.
_LOCK_PREFIX = "pry:cache:lock:"
_LOCK_TTL_MS = 5_000
_POLL_SECONDS = 0.05
# Per-key asyncio locks (one per event loop; process-local is the point).
_FLIGHT_LOCKS: dict[str, list[Any]] = {}
_FLIGHT_GUARD = threading.Lock()
logger = logging.getLogger(__name__)


def _flight_lock(key: str) -> tuple[asyncio.Lock, list[Any]]:
    """Per-key asyncio lock, reference-counted so the map cannot grow."""
    with _FLIGHT_GUARD:
        entry = _FLIGHT_LOCKS.get(key)
        if entry is None:
            entry = [asyncio.Lock(), 0]
            _FLIGHT_LOCKS[key] = entry
        entry[1] += 1
        return entry[0], entry


def _release_flight_lock(key: str, entry: list[Any]) -> None:
    """Drop a waiter; the entry goes once nobody holds or waits on it."""
    with _FLIGHT_GUARD:
        entry[1] -= 1
        if entry[1] <= 0 and not entry[0].locked() and _FLIGHT_LOCKS.get(key) is entry:
            _FLIGHT_LOCKS.pop(key, None)


async def _acquire(cache: Any, key: str) -> tuple[Any, str, str]:
    """Redis ``SET NX PX`` guard: (client, lock_key, token).

    Token is ``""`` when another replica holds the guard, so the caller waits.
    Client is ``None`` when Redis is unavailable — then there is nothing to
    coordinate with and the caller loads directly.
    """
    client = await cache._get_redis()
    if client is None:
        return None, "", ""
    lock_key, token = f"{_LOCK_PREFIX}{key}", uuid.uuid4().hex
    try:
        if await client.set(lock_key, token, nx=True, px=_LOCK_TTL_MS):
            return client, lock_key, token
    except Exception as e:  # noqa: BLE001 — the guard is best-effort
        cache._drop_redis(e)
        return None, "", ""
    return client, lock_key, ""


async def _release(cache: Any, client: Any, lock_key: str, token: str) -> None:
    """Release the guard only if we still own it (best-effort)."""
    if not token:
        return
    try:
        if await client.get(lock_key) == token:
            await client.delete(lock_key)
    except Exception as e:  # noqa: BLE001 — an expiring PX guard is harmless
        logger.debug("response_cache_lock_release_failed", extra={"error": str(e)[:120]})


async def _wait_for_winner(
    cache: Any, client: Any, lock_key: str, url: str, options: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Poll for the guard holder's write; None once its PX TTL lapses."""
    deadline = time.monotonic() + _LOCK_TTL_MS / 1000
    while time.monotonic() < deadline:
        await asyncio.sleep(_POLL_SECONDS)
        hit = await cache.aget(url, options)
        if hit is not None:
            return hit
        if not await client.exists(lock_key):
            break
    return None


async def _load_and_store(
    cache: Any,
    url: str,
    options: dict[str, Any] | None,
    loader: Any,
    ttl: int,
) -> dict[str, Any]:
    """Run the loader once and write the result through to both tiers."""
    data = await loader()
    await cache.aset(url, data, options, ttl=ttl)
    return data


async def _coalesced(
    cache: Any,
    url: str,
    options: dict[str, Any] | None,
    loader: Any,
    ttl: int,
) -> dict[str, Any]:
    """Body of the critical section: recheck, guard, wait, load."""
    hit = await cache.aget(url, options)
    if hit is not None:
        return hit
    client, lock_key, token = await _acquire(cache, cache._key(url, options))
    try:
        if client is not None and not token:
            winner = await _wait_for_winner(cache, client, lock_key, url, options)
            if winner is not None:
                return winner
        return await _load_and_store(cache, url, options, loader, ttl)
    finally:
        if token:
            await _release(cache, client, lock_key, token)


async def fetch_or_load(
    cache: Any,
    url: str,
    options: dict[str, Any] | None,
    loader: Any,
    ttl: int = 300,
) -> dict[str, Any]:
    """One loader run per cold key, process- and cluster-wide."""
    hit = await cache.aget(url, options)
    if hit is not None:
        return hit
    key = cache._key(url, options)
    lock, entry = _flight_lock(key)
    try:
        async with lock:
            return await _coalesced(cache, url, options, loader, ttl)
    finally:
        _release_flight_lock(key, entry)
