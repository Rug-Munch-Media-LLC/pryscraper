"""URL validation: scheme, credentials, traversal and SSRF policy.

Validates URLs before scraping to prevent:
- SSRF attacks (private IPs, loopback, internal hosts)
- Path traversal (../, encoded variants)
- File:// or other non-HTTP schemes
- DNS rebinding risks (common internal hostnames)

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import urlparse

from pry.core.errors import InvalidRequestError
from pry.engine.url_guard.url_host import _validate_host

logger = logging.getLogger(__name__)

# Blocked URL schemes
_ALLOWED_SCHEMES = {"http", "https"}

# Path traversal patterns
_TRAVERSAL_RE = re.compile(
    r"(?:^|/)\.\.(?:/|%2[fF]|\\|$)"
    r"|%2[eE]%2[eE]"
    r"|%252[eE]%252[eE]%252[fF]"
    r"|\.\.(?:/|\\|$)"
)


def _error(message: str, url: str) -> Exception:
    """Build a structured InvalidRequestError."""
    logger.warning("url_guard_rejected", extra={"url": url, "reason": message})
    return InvalidRequestError(message, details={"url": url, "reason": message})


def _parse_url_shape(url: str) -> tuple:
    """Parse the URL and reject unsafe *shape* (scheme, creds, empty host)."""
    if not url:
        raise _error("URL is empty", url)
    try:
        parsed = urlparse(url)
    except ValueError:
        # e.g. "http://[" — Python 3.12 urlparse raises on malformed IPv6
        raise _error("URL has a malformed host", url) from None
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise _error(
            f"URL scheme {parsed.scheme} is not allowed (only http/https)", url
        )
    if parsed.username or parsed.password:
        raise _error("URL must not contain embedded credentials (user:password@)", url)
    try:
        hostname = parsed.hostname or ""
    except ValueError:
        raise _error("URL has a malformed host", url) from None
    if not hostname:
        raise _error("URL must have a valid hostname", url)
    return parsed, hostname


def _check_host(hostname: str, resolve_dns: bool, url: str) -> None:
    try:
        _validate_host(hostname, resolve_dns=resolve_dns, error_cls=InvalidRequestError)
    except InvalidRequestError as e:
        raise _error(str(e), url) from None


def validate_url(url: str, *, resolve_dns: bool = True) -> str:
    """Validate a URL for SSRF and path-traversal safety.

    Args:
        url: The URL to validate.
        resolve_dns: If True, perform a DNS lookup to check that the resolved
                     IP is not in a private range (blocks DNS-rebinding/SSRF).

    Returns:
        The validated URL (unchanged).

    Raises:
        InvalidRequestError: If the URL is unsafe.
    """
    parsed, hostname = _parse_url_shape(url)
    _check_host(hostname, resolve_dns, url)
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


__all__ = [
    "_ALLOWED_SCHEMES",
    "_TRAVERSAL_RE",
    "_error",
    "validate_redirect_url",
    "validate_url",
    "validate_url_async",
]
