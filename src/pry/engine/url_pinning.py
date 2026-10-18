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


async def _pinned_get(
    client: httpx.AsyncClient, url: str, kwargs: dict[str, Any]
) -> httpx.Response:
    """GET *url* with the validated IP pinned as the connect target."""
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
            return await client.send(request, stream=stream)
    # Test doubles and other client shapes: plain GET (no streaming).
    return await client.get(pinned, headers=merged, **kwargs)


async def pinned_get(client: httpx.AsyncClient, url: str, kwargs: dict[str, Any]) -> httpx.Response:
    """GET *url* with the validated IP pinned as the connect target."""
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
            return await client.send(request, stream=stream)
    # Test doubles and other client shapes: plain GET (no streaming).
    return await client.get(pinned, headers=merged, **kwargs)
