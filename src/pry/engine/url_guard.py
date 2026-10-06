"""SSRF and path traversal guard for Pry scrapers.

Validates URLs before scraping to prevent:
- SSRF attacks (private IPs, loopback, internal hosts)
- Path traversal (../, encoded variants)
- File:// or other non-HTTP schemes
- DNS rebinding risks (common internal hostnames)
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlparse

from pry.core.errors import InvalidRequestError

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)

# Private/reserved IP ranges (RFC 1918, RFC 6598, RFC 4193, link-local, loopback)
_PRIVATE_NETS: list[str] = [
    "0.0.0.0/8",  # "this network" (RFC 1122) — 0.0.0.0 is a common SSRF bypass
    "127.0.0.0/8",  # loopback
    "10.0.0.0/8",  # RFC 1918
    "172.16.0.0/12",  # RFC 1918
    "192.168.0.0/16",  # RFC 1918
    "100.64.0.0/10",  # RFC 6598 (CGNAT)
    "169.254.0.0/16",  # link-local (incl. 169.254.169.254 cloud metadata)
    "fc00::/7",  # RFC 4193 (ULA)
    "fe80::/10",  # link-local IPv6
    "::1/128",  # IPv6 loopback
    "::ffff:0:0/96",  # IPv4-mapped IPv6 (::ffff:a.b.c.d) — SSRF bypass vector
]

# Common internal hostnames that suggest SSRF targeting
_INTERNAL_HOST_RE = re.compile(
    r"^(.+\.)?"
    r"(localhost|internal|intranet|private|corp|home|router|gateway|"
    r"metadata|kubernetes|kube|docker|consul|nomad|vault|"
    r"elasticsearch|redis|mysql|postgres|memcached|"
    r"grafana|prometheus|alertmanager|"
    r"minio|s3|storage|db|database|"
    r"admin|dashboard|management|"
    r"apiserver|etcd|"
    r"tailscale|100\.\d+\.\d+\.\d+)"
    r"(\..+)?$",
    re.IGNORECASE,
)

# Blocked URL schemes
_ALLOWED_SCHEMES = {"http", "https"}

# Path traversal patterns
_TRAVERSAL_RE = re.compile(
    r"(?:^|/)\.\.(?:/|%2[fF]|\\|$)"
    r"|%2[eE]%2[eE]"
    r"|%252[eE]%252[eE]%252[fF]"
    r"|\.\.(?:/|\\|$)"
)


def _validate_host(
    hostname: str,
    *,
    resolve_dns: bool = True,
    error_cls: type[Exception] = ValueError,
) -> list[str]:
    """Validate a hostname for SSRF safety.

    Shared by :func:`validate_url` and ``websocket_scraper.validate_websocket_url``.
    Checks the raw IP literal, internal-hostname patterns, and (optionally) DNS
    resolution against private/reserved ranges. Returns the resolved IPs (empty
    when DNS is skipped or fails) or raises ``error_cls`` on a hit.

    Args:
        hostname: The host portion of a URL (no port, no brackets).
        resolve_dns: If True, resolve the hostname and reject any private IP.
        error_cls: Exception class to raise on a rejected host.

    Returns:
        The list of resolved IP addresses (empty when DNS is skipped/fails).

    Raises:
        error_cls: If the host is a private/reserved IP, an internal hostname,
            or resolves to a private IP.
    """
    # Raw IP literal: reject private/reserved ranges (loopback, link-local,
    # metadata, CGNAT, ULA, IPv4-mapped IPv6, ...).
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        # Not an IP literal — continue with hostname checks.
        logger.warning("silent_exception_swallowed", exc_info=True)
    else:
        for net in _PRIVATE_NETS:
            if ip in ipaddress.ip_network(net):
                raise error_cls(f"URL resolves to a private/reserved IP range ({net})")

    # Internal/sensitive hostname patterns (localhost, metadata.*, *.internal, ...).
    if _INTERNAL_HOST_RE.match(hostname):
        raise error_cls(f"URL hostname {hostname} appears to be an internal resource")

    resolved: list[str] = []
    if resolve_dns:
        try:
            addrs = socket.getaddrinfo(hostname, None)
        except OSError as e:
            logger.debug("dns_lookup_failed", extra={"hostname": hostname, "error": str(e)})
            return resolved
        for _family, _type, _proto, _canonname, sockaddr in addrs:
            addr = str(sockaddr[0])
            try:
                ip = ipaddress.ip_address(addr)
            except ValueError:
                logger.warning("silent_exception_swallowed", exc_info=True)
                continue
            for net in _PRIVATE_NETS:
                if ip in ipaddress.ip_network(net):
                    raise error_cls(f"URL resolves to private IP {addr} ({net})")
            resolved.append(addr)
    return resolved


def validate_url(url: str, *, resolve_dns: bool = True) -> str:
    """Validate a URL for SSRF and path-traversal safety.

    Args:
        url: The URL to validate.
        resolve_dns: If True, perform a DNS lookup to check that the resolved
                     IP is not in a private range. This adds latency and cannot
                     be async here. It defaults to True so DNS-rebinding/SSRF
                     vectors (e.g. a hostname that resolves to 169.254.169.254)
                     are blocked by default. Pass resolve_dns=False only when a
                     caller has already resolved and vetted the address.

    Returns:
        The validated URL (unchanged).

    Raises:
        InvalidRequestError: If the URL is unsafe.
    """
    if not url:
        raise _error("URL is empty", url)

    try:
        parsed = urlparse(url)
    except ValueError:
        # e.g. "http://[" — Python 3.12 urlparse raises on malformed IPv6
        raise _error("URL has a malformed host", url) from None

    # Reject non-HTTP schemes
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise _error(
            f"URL scheme {parsed.scheme} is not allowed (only http/https)",
            url,
        )

    # Reject URLs with embedded credentials
    if parsed.username or parsed.password:
        raise _error("URL must not contain embedded credentials (user:password@)", url)

    try:
        hostname = parsed.hostname or ""
    except ValueError:
        # e.g. "http://[" — urllib raises ValueError parsing the IPv6 bracket
        raise _error("URL has a malformed host", url) from None

    # Reject empty hostnames
    if not hostname:
        raise _error("URL must have a valid hostname", url)

    # Reject raw private IPs, internal hostnames, and DNS resolution to
    # private IPs (shared host-validation logic).
    try:
        _validate_host(hostname, resolve_dns=resolve_dns, error_cls=InvalidRequestError)
    except InvalidRequestError as e:
        raise _error(str(e), url) from None

    # Check path for traversal attempts
    path = parsed.path + parsed.params + parsed.query + parsed.fragment
    if _TRAVERSAL_RE.search(path):
        raise _error("URL contains path traversal sequences", url)

    return url


async def validate_url_async(url: str, *, resolve_dns: bool = True) -> str:
    """Async variant of :func:`validate_url` that does not block the event loop.

    ``validate_url`` performs a synchronous DNS lookup (``socket.getaddrinfo``)
    when ``resolve_dns`` is True, which blocks the event loop when called from
    async scrape paths (every tier attempt + every redirect). This wrapper runs
    the synchronous validation in a worker thread via ``asyncio.to_thread`` so
    the event loop stays responsive.

    Args:
        url: The URL to validate.
        resolve_dns: If True, perform a DNS lookup to check that the resolved
            IP is not in a private range (same semantics as :func:`validate_url`).

    Returns:
        The validated URL (unchanged).

    Raises:
        InvalidRequestError: If the URL is unsafe.
    """
    return await asyncio.to_thread(validate_url, url, resolve_dns=resolve_dns)


def validate_redirect_url(url: str) -> str:
    """Re-validate a redirect target URL before following it.

    Redirects are attacker-controlled: a 302 to 127.0.0.1, 169.254.169.254,
    or an internal hostname must never be followed. DNS resolution is always
    enabled here, regardless of :func:`validate_url` defaults.

    Returns:
        The validated redirect target (unchanged).

    Raises:
        InvalidRequestError: If the redirect target is unsafe.
    """
    return validate_url(url, resolve_dns=True)


async def safe_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_redirects: int = 10,
    **kwargs: Any,
) -> httpx.Response:
    """Perform an HTTP GET with SSRF-safe redirect re-validation.

    Redirects are followed manually so every Location target is re-validated
    (including DNS resolution) before the next hop. A redirect to a private,
    loopback, link-local, or metadata IP raises ``InvalidRequestError`` and
    aborts the chain. Callers must pass a client constructed without
    ``follow_redirects=True`` (the httpx default is False).

    Args:
        client: httpx AsyncClient used for the request.
        url: Initial URL (validated here before the first request).
        max_redirects: Hard cap on redirect hops (default 10).
        **kwargs: Extra kwargs forwarded to every ``client.get()`` call.

    Returns:
        The final (non-redirect) httpx.Response.
    """
    validate_url(url)
    response = await client.get(url, **kwargs)
    redirects = 0
    while response.is_redirect and redirects < max_redirects:
        location = response.headers.get("location")
        if not location:
            break
        target = urljoin(str(response.url), location)
        validate_redirect_url(target)
        response = await client.get(target, **kwargs)
        redirects += 1
    return response


def _error(message: str, url: str) -> Exception:
    """Build a structured InvalidRequestError."""
    logger.warning("url_guard_rejected", extra={"url": url, "reason": message})
    return InvalidRequestError(message, details={"url": url, "reason": message})
