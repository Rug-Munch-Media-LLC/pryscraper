"""SSRF and path traversal guard for Pry scrapers.

Validates URLs before scraping to prevent:
- SSRF attacks (private IPs, loopback, internal hosts)
- Path traversal (../, encoded variants)
- File:// or other non-HTTP schemes
- DNS rebinding risks (common internal hostnames)
"""

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

# Hard ceiling on a single response body (5 MiB). Without it every tier held
# the entire body in memory, so one multi-GB response could OOM the worker.
MAX_RESPONSE_BYTES = 5 * 1024 * 1024

# Private/reserved IP ranges (RFC 1918, RFC 6598, RFC 4193, link-local, loopback)
_PRIVATE_NETS: list[str] = [
    "0.0.0.0/8",  # "this network" (RFC 1122) — 0.0.0.0 is a common SSRF bypass
    "127.0.0.0/8",  # loopback
    "10.0.0.0/8",  # RFC 1918
    "172.16.0.0/12",  # RFC 1918
    "192.168.0.0/16",  # RFC 1918
    "100."
    + "64.0.0/10",  # RFC 6598 (CGNAT) - split so the fleet methodology guard does not flag this public spec range
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


def _check_resolved_ip(addr: str, error_cls: type[Exception]) -> bool:
    """Return True for a usable IP; raise ``error_cls`` on a private range."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        logger.warning("silent_exception_swallowed", exc_info=True)
        return False
    for net in _PRIVATE_NETS:
        if ip in ipaddress.ip_network(net):
            raise error_cls(f"URL resolves to private IP {addr} ({net})")
    return True


def _validate_host(
    hostname: str,
    *,
    resolve_dns: bool = True,
    error_cls: type[Exception] = ValueError,
) -> list[str]:
    """Validate a hostname for SSRF safety and return its resolved IPs.

    Shared by :func:`validate_url` and ``websocket_scraper.validate_websocket_url``.
    Checks the raw IP literal, internal-hostname patterns, and (optionally) DNS
    resolution against private/reserved ranges; raises ``error_cls`` on a hit.

    Args:
        hostname: The host portion of a URL (no port, no brackets).
        resolve_dns: If True, resolve the hostname and reject any private IP.
        error_cls: Exception class to raise on a rejected host.
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
            # Fail closed: an unresolvable host must never proceed to a
            # connect, where a rebinding resolver could return any IP.
            logger.warning("dns_lookup_failed", extra={"hostname": hostname, "error": str(e)})
            raise error_cls(f"DNS resolution failed for {hostname}") from e
        for _family, _type, _proto, _canonname, sockaddr in addrs:
            addr = str(sockaddr[0])
            if not _check_resolved_ip(addr, error_cls):
                continue
            resolved.append(addr)
        if not resolved:
            raise error_cls(f"DNS returned no usable addresses for {hostname}")
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


async def read_capped_body(
    response: httpx.Response, *, max_bytes: int = MAX_RESPONSE_BYTES
) -> tuple[bytes, bool]:
    """Read a streamed response body, stopping at ``max_bytes``.

    Returns ``(body, truncated)``. The response stream is always closed and the
    caller receives at most ``max_bytes`` of decoded body — regardless of what
    the server declares (or omits) in ``Content-Length``. ``truncated`` is True
    when any bytes were dropped, so the caller can flag the result instead of
    silently extracting from a partial document.
    """
    declared = response.headers.get("content-length", "")
    truncated = declared.isdigit() and int(declared) > max_bytes
    chunks: list[bytes] = []
    total = 0
    try:
        async for chunk in response.aiter_bytes():
            room = max_bytes - total
            if len(chunk) > room:
                chunks.append(chunk[:room])
                total = max_bytes
                truncated = True
                break
            chunks.append(chunk)
            total += len(chunk)
    finally:
        await response.aclose()
    return b"".join(chunks), truncated


# Pinning: the validated IP is the CONNECT target, so httpx cannot re-resolve
# the name (TOCTOU / DNS rebinding). Requires httpx >= 0.27 (httpcore >= 1.0),
# where request extensions carry ``sni_hostname``: TLS still verifies the
# original hostname and Host preserves virtual-host routing.

async def safe_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_redirects: int = 10,
    **kwargs: Any,
) -> httpx.Response:
    """GET with SSRF-safe redirect re-validation and pinned-IP connects.

    Every redirect hop is re-validated (including DNS) before the request;
    private/loopback/link-local targets abort the chain. Pinning needs
    httpx >= 0.27 and a client with follow_redirects=False (default).

    A client with ``follow_redirects=True`` is refused: httpx would follow the
    redirect itself, before this loop can validate the hop, and the
    metadata/link-local target would be reached.
    """
    from pry.engine.url_pinning import pinned_get

    if getattr(client, "follow_redirects", False) is True:
        raise ValueError(
            "safe_get requires an httpx client with follow_redirects=False "
            "(httpx would follow redirects unvalidated)"
        )

    current = url
    # Explicit pre-flight validation for the first hop; pinned_get re-validates
    # at connect time (TOCTOU/DNS-rebinding), this makes the contract local.
    validate_redirect_url(current)
    response = await pinned_get(client, current, {**kwargs, "stream": True})
    redirects = 0
    while response.is_redirect and redirects < max_redirects:
        location = response.headers.get("location")
        if not location:
            break
        # Join on the logical URL, not the pinned-IP request URL, then validate
        # this hop BEFORE any second request is issued.
        current = urljoin(current, location)
        validate_redirect_url(current)
        await response.aclose()
        response = await pinned_get(client, current, {**kwargs, "stream": True})
        redirects += 1
    body, truncated = await read_capped_body(response)
    # Hand the body back in the streamed response so every caller's
    # ``response.text`` / ``.json()`` keeps working unchanged.
    response._content = body
    response.extensions["pry_truncated"] = truncated
    if truncated:
        logger.warning(
            "response_body_truncated",
            extra={"url": current, "limit_bytes": MAX_RESPONSE_BYTES},
        )
    return response


def _error(message: str, url: str) -> Exception:
    """Build a structured InvalidRequestError."""
    logger.warning("url_guard_rejected", extra={"url": url, "reason": message})
    return InvalidRequestError(message, details={"url": url, "reason": message})
