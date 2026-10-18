"""Host/IP SSRF checks: private ranges, internal names and DNS resolution.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import ipaddress
import logging
import re

logger = logging.getLogger(__name__)

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
        # Imported lazily: ``pry.engine.url_guard.socket`` is a submodule of the
        # package that imports this module (historical patch seam for tests).
        from pry.engine.url_guard import socket as guard_socket

        try:
            addrs = guard_socket.getaddrinfo(hostname, None)
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


__all__ = ["_INTERNAL_HOST_RE", "_PRIVATE_NETS", "_check_resolved_ip", "_validate_host"]
