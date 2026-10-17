"""Pry — webhook URL validation and redaction helpers."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
import ipaddress
import logging
import os
import socket
import urllib.parse
from typing import Any

from pry.core.settings import settings

logger = logging.getLogger(__name__)


def resolve_secret(explicit: str) -> tuple[str, str]:
    """Return (secret, origin) following explicit -> env -> settings."""
    if explicit:
        return explicit, "explicit"
    env = os.getenv("PRY_WEBHOOK_SECRET")
    if env:
        return env, "env"
    if settings.webhook_secret:
        return settings.webhook_secret, "settings"
    return "", "missing"


_REDACT_KEYS = ("token", "secret", "password", "api_key", "authorization")
_PRODUCTION_ENVS = frozenset({"production", "prod"})


def _is_production() -> bool:
    env = (os.getenv("PRY_ENV") or os.getenv("ENVIRONMENT") or "").strip().lower()
    return env in _PRODUCTION_ENVS


def _redact(value: Any) -> Any:
    """Recursively redact sensitive keys in nested objects and arrays."""
    if isinstance(value, dict):
        return {
            k: ("***REDACTED***" if any(n in str(k).lower() for n in _REDACT_KEYS) else _redact(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(v) for v in value]
    return value


def _check_scheme(parsed: urllib.parse.ParseResult) -> str | None:
    if not parsed.hostname:
        return "missing hostname"
    scheme = parsed.scheme.lower()
    if scheme not in ("https", "http"):
        return f"unsupported scheme: {scheme}"
    if scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        return "http only allowed for localhost"
    return None


def _resolve_public(hostname: str) -> tuple[str | None, str | None]:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        logger.warning("webhook_delivery_exception_handler", exc_info=True)
        return None, "hostname unresolvable"
    first: str | None = None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return None, f"host resolves to private/loopback IP: {ip}"
        first = first or str(ip)
    return (first, None) if first else (None, "hostname unresolvable")


def _validate_url(url: str) -> tuple[None, str] | tuple[str, None]:
    """Return (pinned_url, None) when safe, or (None, reason)."""
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        logger.warning("webhook_delivery_exception_handler", exc_info=True)
        return None, "invalid URL"
    reason = _check_scheme(parsed)
    if reason:
        return None, reason
    ip, reason = _resolve_public(parsed.hostname or "")
    if reason or ip is None:
        return None, reason or "hostname unresolvable"
    host_literal = f"[{ip}]" if ":" in ip else ip
    netloc = f"{host_literal}:{parsed.port}" if parsed.port else host_literal
    return parsed._replace(netloc=netloc).geturl(), None


async def retry_dead_letter_async(delivery: Any, limit: int) -> dict[str, Any]:
    """Replay dead-lettered webhooks through the signed delivery path."""
    items = delivery.get_dead_letter()
    batch, keep = items[:limit], items[limit:]
    delivered = failed = 0
    for item in batch:
        result = await delivery.deliver(
            item.get("url", ""),
            item.get("payload", {}),
            event_type=item.get("event", "monitor.change"),
            max_retries=1,
            record_dead_letter=False,
        )
        if result.get("success"):
            delivered += 1
        else:
            failed += 1
            keep.append(item)
    delivery._write_dead_letter(keep)
    return {
        "total": len(items),
        "attempted": len(batch),
        "delivered": delivered,
        "failed": failed,
        "items": keep,
    }


def retry_dead_letter(delivery: Any, limit: int = 20) -> dict[str, Any]:
    """Sync wrapper that works inside and outside a running event loop."""
    import asyncio
    import concurrent.futures

    coro = retry_dead_letter_async(delivery, limit)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


class WebhookSecretNotConfigured(RuntimeError):
    """Raised when signing is attempted without a configured secret."""
