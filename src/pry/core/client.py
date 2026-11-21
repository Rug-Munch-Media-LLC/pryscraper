"""Pry — shared httpx client pool with connection reuse.

All modules should import ``get_client`` from here (or from ``pry.api.client``
which re-exports for backward compatibility) instead of creating new clients.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

_default_limits = httpx.Limits(
    max_connections=100,
    max_keepalive_connections=20,
    keepalive_expiry=30,
)

_default_timeout = httpx.Timeout(
    connect=10.0,
    read=60.0,
    write=30.0,
    pool=10.0,
)

http_client: httpx.AsyncClient | None = None

#: The loop the shared client was built on. An ``httpx.AsyncClient`` is bound to
#: the loop that created it (its connection pool and its ``asyncio.Lock`` are),
#: so a client built under one loop cannot be used from another -- it fails with
#: "RuntimeError: Event loop is closed" or silently returns stale results. That
#: is what made six tests fail only in a full run and pass in isolation: the
#: first test's loop died, and every later test reused its corpse because
#: ``is_closed`` stayed False.
_client_loop: asyncio.AbstractEventLoop | None = None

#: Guards the double-checked creation below. Module-level so it exists before the
#: first call, and REPLACED by get_client() when the running loop changes (an
#: asyncio.Lock is bound to the loop that created it, so a lock from a dead loop
#: raises "attached to a different loop"). My earlier edit dropped this line while
#: moving the lock into the loop-change branch, which left the name undefined on
#: first use -- mypy caught it, the tests did not, because every test that hit
#: this path had already created the client once.
_client_lock = asyncio.Lock()


async def get_client() -> httpx.AsyncClient:
    """Get or create the shared httpx client FOR THE CURRENT EVENT LOOP.

    Uses a double-checked locking pattern guarded by ``_client_lock`` so that
    concurrent first-calls cannot both create an ``AsyncClient`` and orphan the
    loser (which would leak its connection pool / file descriptors).

    The client is rebuilt when the running loop differs from the one it was
    created on. Without that, a long-lived process that rotates loops (tests,
    and any host that restarts its loop) keeps a client whose transport points
    at a closed loop; every request through it then raises
    "Event loop is closed" rather than opening a new connection.
    """
    global http_client, _client_lock, _client_loop
    try:
        loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop in this thread. get_client() is documented as async,
        # so this only happens when it is called from sync context by mistake --
        # worth a debug line rather than a silent bind to a thread-local loop.
        logger.debug("get_client_without_running_loop")
        loop = None
    if http_client is not None and not http_client.is_closed and _client_loop is loop:
        return http_client
    # The lock is ALSO loop-bound; recreating it when the loop changes keeps the
    # double-checked section usable instead of raising "attached to a different
    # loop" on the first concurrent call.
    if _client_loop is not loop:
        _client_lock = asyncio.Lock()
        http_client = None
        _client_loop = loop
    async with _client_lock:
        if http_client is not None and not http_client.is_closed and _client_loop is loop:
            return http_client
        http_client = httpx.AsyncClient(
            timeout=_default_timeout,
            limits=_default_limits,
            headers={"User-Agent": "pry/3.0"},
            # retries=0: disable httpx's automatic retry-on-connection-error so
            # the caller's own retry loop (e.g. WebhookDelivery.deliver) is the
            # single source of retry behavior.
            transport=httpx.AsyncHTTPTransport(retries=0),
        )
        _client_loop = loop
        return http_client


async def close_client() -> None:
    """Close the shared client on shutdown.

    Shutdown must not raise. The client may have been built on a loop that has
    already closed (TestClient contexts, and any host that tears the loop down
    before running lifespan shutdown), in which case ``aclose()`` raises
    "RuntimeError: Event loop is closed" out of the lifespan and turns a clean
    exit into a traceback. The global is cleared either way -- a client that
    cannot be closed on this loop is unusable on the next one.
    """
    global http_client
    client, http_client = http_client, None
    if client is None or client.is_closed:
        return
    try:
        await client.aclose()
    except RuntimeError as exc:
        logger.warning("http_client_close_skipped", extra={"error": str(exc)})
