"""Pry — shared httpx client pool with connection reuse.
All modules import `http_client` instead of creating new clients per request."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

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


async def get_client() -> httpx.AsyncClient:
    """Get or create the shared httpx client."""
    global http_client
    if http_client is None or http_client.is_closed:
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
