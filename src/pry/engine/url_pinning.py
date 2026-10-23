"""SSRF-safe connection pinning for outbound HTTP fetches.

Kept separate from url_guard so validation and connection policy can evolve
independently and neither module exceeds the structure gate's size ceiling.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
import asyncio
from typing import Any
from urllib.parse import urlparse

import httpx

from pry.core.errors import InvalidRequestError
from pry.engine.url_guard import _error, _validate_host, validate_url


def pin_request(url: str) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Validate *url* once and return (pinned_url, headers, extensions)."""
    try:
        validate_url(url, resolve_dns=False)
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        addresses = _validate_host(hostname, resolve_dns=True, error_cls=InvalidRequestError)
    except InvalidRequestError as exc:
        raise _error(str(exc), url) from None
    if not addresses:
        # Host was already an IP literal; it was validated, nothing to pin.
        return url, {}, {}
    netloc, host = _pinned_netloc(parsed, addresses[0])
    extensions: dict[str, Any] = {}
    if parsed.scheme == "https":
        extensions["sni_hostname"] = parsed.hostname or ""
    return parsed._replace(netloc=netloc).geturl(), {"Host": host}, extensions


def _pinned_netloc(parsed: Any, address: str) -> tuple[str, str]:
    netloc = f"[{address}]" if ":" in address else address
    try:
        port = parsed.port
    except ValueError as exc:
        raise _error(f"URL has a malformed port: {exc}", parsed.geturl()) from None
    default_port = 443 if parsed.scheme == "https" else 80
    if port and port != default_port:
        netloc = f"{netloc}:{port}"
    host = parsed.hostname or ""
    if port and port != default_port:
        host = f"{host}:{port}"
    return netloc, host


async def pinned_get(
    client: httpx.AsyncClient,
    url: str,
    kwargs: dict[str, Any],
    *,
    pin_connections: bool = True,
) -> httpx.Response:
    """GET *url* with the validated IP pinned as the connect target.

    The connect URL carries the validated IP, but the cookie jar must stay
    keyed on the logical host: httpx keys cookies by the request URL, so a
    pinned request would otherwise store/send cookies under the resolved IP
    (which changes on the next DNS answer and silently drops the session).

    ``pin_connections=False`` keeps the logical hostname in the request URL.
    Required when the client routes through an HTTP(S) proxy: httpcore's
    CONNECT-tunnel path ignores the ``sni_hostname`` extension (measured on
    httpx 0.28.1 / httpcore 1.0.9), so a pinned URL sends the resolved IP as
    the TLS SNI and every hop fails the handshake. URL validation still runs
    per hop in :func:`safe_get`; only the connect-time pinning is dropped.
    """
    if not pin_connections:
        stream = bool(kwargs.pop("stream", False))
        headers = kwargs.pop("headers", None) or {}
        build = getattr(client, "build_request", None)
        if callable(build):
            request = build("GET", url, headers=headers, **kwargs)
            return await client.send(request, stream=stream)
        return await client.get(url, headers=headers, **kwargs)
    pinned, headers, extensions = await asyncio.to_thread(pin_request, url)
    merged = {**(kwargs.pop("headers", None) or {}), **headers}
    if extensions:
        kwargs["extensions"] = {**(kwargs.pop("extensions", None) or {}), **extensions}
    # httpx 0.28 removed the ``stream`` kwarg from AsyncClient.get(); a streamed
    # GET must be built and sent explicitly. Callers (safe_get) need streaming so
    # the body can be capped, and every guarded fetch was raising TypeError.
    stream = bool(kwargs.pop("stream", False))
    build = getattr(client, "build_request", None)
    if callable(build):
        request = build("GET", pinned, headers=merged, **kwargs)
        if isinstance(request, httpx.Request):
            _send_logical_cookies(client, request, url)
            response = await client.send(request, stream=stream)
            _absorb_logical_cookies(client, response, url)
            return response
    # Test doubles and other client shapes: plain GET (no streaming).
    return await client.get(pinned, headers=merged, **kwargs)


def _send_logical_cookies(client: Any, request: httpx.Request, url: str) -> None:
    """Attach the jar's cookies for the *logical* host to a pinned request."""
    jar = getattr(client, "cookies", None)
    if jar is None or not hasattr(jar, "set_cookie_header"):
        return
    probe = httpx.Request("GET", url)
    jar.set_cookie_header(probe)
    header = probe.headers.get("cookie")
    if header:
        request.headers["cookie"] = header


def _absorb_logical_cookies(client: Any, response: httpx.Response, url: str) -> None:
    """Store ``Set-Cookie`` from a pinned response under the logical host.

    ``client.send`` already filed the response cookies under the pinned IP;
    drop those so the jar holds exactly one entry per cookie, keyed by the
    real hostname (a duplicate would make ``Cookies.get`` raise).
    """
    jar = getattr(client, "cookies", None)
    if jar is None or not hasattr(jar, "extract_cookies"):
        return
    pinned_host = getattr(getattr(response, "request", None), "url", None)
    if pinned_host is not None:
        _drop_host_cookies(jar, pinned_host.host)
    probe = httpx.Response(
        response.status_code,
        headers=response.headers,
        request=httpx.Request("GET", url),
    )
    jar.extract_cookies(probe)


def _drop_host_cookies(jar: Any, host: str) -> None:
    """Remove jar entries filed under *host* (the pinned IP).

    ``http.cookiejar`` files an IPv6 literal as ``[addr].local`` (and an IPv4
    literal as the bare address), so match every spelling.
    """
    cookiejar = getattr(jar, "jar", None)
    if cookiejar is None:
        return
    targets = {host, f"[{host}]", f"[{host}].local"}
    for cookie in list(cookiejar):
        if cookie.domain in targets:
            cookiejar.clear(cookie.domain, cookie.path, cookie.name)
