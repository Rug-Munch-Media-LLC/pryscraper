"""Tor fallback — fetch a URL through a local Tor SOCKS5 proxy.

Standalone helper used as the last-resort tier of the scrape fallback
chain (see ``ultimate_scraper._tier_tor``). The ``aiohttp-socks``
package is read lazily so this module imports cleanly even when the
dependency is absent; every function degrades to ``None``/``False``
instead of raising.

Design notes:

* ``fetch_via_tor`` never raises — any failure (missing dependency,
  unreachable proxy, connection error, timeout, non-200 response)
  returns ``None`` so callers can fall through to the next tier.
* ``tor_available`` / ``tor_status`` are synchronous TCP probes of the
  SOCKS port, used by ``capabilities`` for the /v1/capabilities report.
* The SOCKS connection is created with ``rdns=True`` so DNS resolution
  happens through Tor (never leaks to the local resolver).

Usage:
    from pry.engine.tor_fallback import fetch_via_tor, tor_available

    if tor_available():
        html = await fetch_via_tor("https://example.com", timeout=30.0)
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import importlib.util
import logging
import socket
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TOR_HOST = "127.0.0.1"
DEFAULT_TOR_PORT = 9050
DEFAULT_TOR_TIMEOUT = 30.0
_SOCKS_PROBE_TIMEOUT = 1.0


def _aiohttp_socks_installed() -> bool:
    """Return True when the optional ``aiohttp-socks`` package is present."""
    try:
        return importlib.util.find_spec("aiohttp_socks") is not None
    except (ImportError, ValueError):
        return False


def _socks_port_reachable(host: str, port: int) -> bool:
    """TCP probe: does a local listener accept connections on the SOCKS port?"""
    try:
        with socket.create_connection((host, port), timeout=_SOCKS_PROBE_TIMEOUT):
            return True
    except OSError:
        return False


def tor_available(tor_host: str = DEFAULT_TOR_HOST, tor_port: int = DEFAULT_TOR_PORT) -> bool:
    """Return True when the Tor SOCKS5 proxy can be used right now.

    Requires both the ``aiohttp-socks`` dependency and a live listener on
    the SOCKS port. Synchronous on purpose — ``capabilities`` calls it
    directly for the /v1/capabilities report.
    """
    if not _aiohttp_socks_installed():
        return False
    return _socks_port_reachable(tor_host, tor_port)


def tor_status(
    tor_host: str = DEFAULT_TOR_HOST, tor_port: int = DEFAULT_TOR_PORT
) -> dict[str, Any]:
    """Return a status dict for monitoring/observability.

    Keys: ``available`` (dependency + reachable port), ``host``,
    ``port``, ``reachable`` (TCP probe result alone).
    """
    installed = _aiohttp_socks_installed()
    reachable = _socks_port_reachable(tor_host, tor_port)
    return {
        "available": installed and reachable,
        "host": tor_host,
        "port": tor_port,
        "reachable": reachable,
    }


async def fetch_via_tor(
    url: str,
    *,
    tor_port: int = DEFAULT_TOR_PORT,
    tor_host: str = DEFAULT_TOR_HOST,
    timeout: float = DEFAULT_TOR_TIMEOUT,  # noqa: ASYNC109 - spec-mandated kwarg name (fetch_via_tor contract)
) -> str | None:
    """Fetch *url* through the local Tor SOCKS5 proxy.

    Returns the HTML text on success, or ``None`` on any failure
    (missing ``aiohttp-socks``, unreachable proxy, connection error,
    timeout, non-200 response). Never raises — callers treat ``None``
    as "try the next fallback tier".
    """
    try:
        import aiohttp
        from aiohttp_socks import ProxyConnector
    except ImportError:
        logger.debug("tor_fallback_unavailable", extra={"reason": "aiohttp-socks not installed"})
        return None

    try:
        connector = ProxyConnector(host=tor_host, port=tor_port, rdns=True)
        async with (
            aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as session,
            session.get(url) as resp,
        ):
            if resp.status != 200:
                return None
            return await resp.text()
    except (aiohttp.ClientError, OSError, TimeoutError) as exc:
        logger.debug("tor_fallback_failed", extra={"error": str(exc)[:100]})
        return None
    except Exception as exc:  # noqa: BLE001 - contract: Tor fallback never raises
        logger.debug("tor_fallback_error", extra={"error": str(exc)[:100]})
        return None
