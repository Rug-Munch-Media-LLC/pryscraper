"""Pry — ASGI middleware facade: auth, rate limiting, timing, logging.

Thin facade re-exporting the focused middleware modules. It also owns the
*stateful* trusted-proxy configuration block: tests ``importlib.reload()``
this module after setting ``PRY_TRUSTED_PROXIES`` and patch
``_TRUSTED_PROXY_NETWORKS`` / ``_is_trusted_proxy`` here, so the network
tuple must be (re)computed in this module's namespace.

* ``PryHttpMiddleware`` — pure-ASGI auth + rate-limit + timing + logging
  (``middleware_http``).
* ``request_authorized`` / ``is_loopback_client`` — fail-closed auth policy
  (``middleware_auth``); routers/proxy.py and routers/config.py import it
  from api.py, which re-exports it from here.
* ``_path_exists`` — route-existence check for the unknown-path 404
  pass-through (``middleware_common``).
* ``_resolve_client_ip`` — trusted-proxy-aware client-IP resolution for the
  rate-limit bucket. ``X-Forwarded-For`` is honored ONLY when the immediate
  socket peer is loopback or listed in ``PRY_TRUSTED_PROXIES``; otherwise the
  socket peer is used, so clients cannot spoof a different rate-limit bucket
  behind nginx.

Trusted proxies: ``PRY_TRUSTED_PROXIES`` env var, comma/space-separated IPs
or CIDR blocks. Loopback peers are always trusted.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import ipaddress
import os
from collections.abc import Mapping
from typing import Any

from pry.commerce.billing.enforcer import billing_enforcer
from pry.core.deps import ratelimiter, user_ratelimiter
from pry.core.middleware_auth import (
    _AUTH_PUBLIC_PATHS,
    _LOOPBACK_OR_TEST_HOSTS,
    is_loopback_client,
    request_authorized,
)
from pry.core.middleware_common import (
    _SECURITY_HEADERS,
    _get_header,
    _path_exists,
    _route_table_root,
    bind_request_id,
    clear_request_id,
    logger,
)
from pry.core.middleware_http import PryHttpMiddleware
from pry.core.middleware_usage import _USAGE_FLUSH_SIZE, _flush_usage, _record_usage, _usage_queue
from pry.core.settings import settings


# ── Trusted-proxy aware rate-limit key ───────────────────────────
# nginx (and other reverse proxies) sit on the loopback interface and forward
# the real client in X-Forwarded-For. Bucketing by scope["client"][0] would
# collapse every user behind the proxy into one bucket. We therefore honor
# X-Forwarded-For ONLY when the immediate socket peer is loopback or an
# explicitly configured trusted proxy — otherwise the header is ignored and
# the socket peer is used, which keeps the header unspoofable.
def _parse_trusted_proxy(
    value: str,
) -> ipaddress.IPv4Network | ipaddress.IPv6Network | None:
    """Parse a single trusted-proxy entry (IP or CIDR). Returns None if invalid."""
    try:
        return ipaddress.ip_network(value, strict=False)
    except ValueError:
        logger.warning("pry_trusted_proxy_invalid", extra={"value": value})
        return None


_TRUSTED_PROXY_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = tuple(
    network
    for part in os.getenv("PRY_TRUSTED_PROXIES", "").replace(",", " ").split()
    if part.strip()
    for network in (_parse_trusted_proxy(part.strip()),)
    if network is not None
)


def _is_trusted_proxy(ip: str) -> bool:
    """Return True when the peer address is in the configured trusted-proxy list."""
    if not ip or ip == "unknown":
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        logger.warning("middleware_exception_handler", exc_info=True)
        return False
    return any(addr in network for network in _TRUSTED_PROXY_NETWORKS)


def _resolve_client_ip(scope: Mapping[str, Any]) -> str:
    """Resolve the effective client IP used for the rate-limit bucket.

    * Default: the socket peer IP (X-Forwarded-For is spoofable).
    * When the immediate socket peer is loopback or a configured trusted
      proxy, honor X-Forwarded-For and use the rightmost non-trusted,
      non-loopback hop — the first hop appended by our own proxy chain,
      which cannot be spoofed by the client.
    """
    client = scope.get("client")
    peer = client[0] if client else ""
    if not peer or peer == "unknown":
        return "unknown"
    if is_loopback_client(peer) or _is_trusted_proxy(peer):
        xff = _get_header(scope, b"x-forwarded-for")
        if xff:
            hops = [h.strip() for h in xff.split(",")]
            for hop in reversed(hops):
                if not hop:
                    continue
                if _is_trusted_proxy(hop):
                    continue
                try:
                    if ipaddress.ip_address(hop).is_loopback:
                        continue
                except ValueError:
                    logger.warning("middleware_exception_handler", exc_info=True)
                    break  # non-IP hop — use it as-is (can't be loopback)
                return hop
    return peer


__all__ = [
    "_AUTH_PUBLIC_PATHS",
    "_LOOPBACK_OR_TEST_HOSTS",
    "_SECURITY_HEADERS",
    "_TRUSTED_PROXY_NETWORKS",
    "_USAGE_FLUSH_SIZE",
    "PryHttpMiddleware",
    "_flush_usage",
    "_get_header",
    "_is_trusted_proxy",
    "_parse_trusted_proxy",
    "_path_exists",
    "_record_usage",
    "_resolve_client_ip",
    "_route_table_root",
    "_usage_queue",
    "billing_enforcer",
    "bind_request_id",
    "clear_request_id",
    "is_loopback_client",
    "logger",
    "ratelimiter",
    "request_authorized",
    "settings",
    "user_ratelimiter",
]
