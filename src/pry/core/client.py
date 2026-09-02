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

_client_lock = asyncio.Lock()


async def get_client() -> httpx.AsyncClient:
    """Get or create the shared httpx client.

    Uses a double-checked locking pattern guarded by ``_client_lock`` so that
    concurrent first-calls cannot both create an ``AsyncClient`` and orphan the
    loser (which would leak its connection pool / file descriptors).
    """
    global http_client
    if http_client is not None and not http_client.is_closed:
        return http_client
    async with _client_lock:
        if http_client is not None and not http_client.is_closed:
            return http_client
        http_client = httpx.AsyncClient(
            timeout=_default_timeout,
            limits=_default_limits,
            headers={"User-Agent": "pry/3.0"},
        )
        return http_client


async def close_client() -> None:
    """Close the shared client on shutdown."""
    global http_client
    if http_client and not http_client.is_closed:
        await http_client.aclose()
    http_client = None
