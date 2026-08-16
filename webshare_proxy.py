"""Pry — Webshare residential proxy pool source/loader.

Loads the Webshare residential proxy list (space-separated
``http://user:pass@host:port`` URLs) from, in priority order:

1. the ``WEBSHARE_PROXY_LIST`` environment variable (12-factor, CI/local dev), or
2. the secrets manager (gopass), path configurable via
   ``PRY_WEBSHARE_GOPASS_PATH`` — best-effort, skipped when
   ``PRY_SECRET_BACKEND`` is explicitly set to ``env``/``file``
   so tests and non-gopass hosts never depend on the real secret.

The resolved list is cached for the process lifetime (mirrors
``secrets_backend`` caching). No credentials are hardcoded here.

Usage:
    from webshare_proxy import load_webshare_proxies, next_webshare_proxy

    pool = load_webshare_proxies()   # cached list[str]
    proxy = next_webshare_proxy()    # round-robin across the pool

Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from functools import lru_cache

logger = logging.getLogger(__name__)

#: Env var holding the space-separated proxy list. Takes precedence over gopass.
WEBSHARE_PROXY_LIST_ENV = "WEBSHARE_PROXY_LIST"
#: Secrets-manager (gopass) path for the Webshare residential proxy list.
#: Override via PRY_WEBSHARE_GOPASS_PATH. The default is a generic name with
#: no internal deployment details (this is an open-source repo).
WEBSHARE_GOPASS_PATH = os.getenv("PRY_WEBSHARE_GOPASS_PATH", "pry/webshare_proxy_list")

_rotation_index = 0
_rotation_lock = threading.Lock()


def parse_proxy_list(raw: str) -> list[str]:
    """Parse a proxy list string into individual proxy URLs.

    Accepts space- and/or newline-separated entries, tolerating extra
    whitespace and blank lines. Malformed entries are preserved as-is so
    the caller can surface them (the pool still filters empties).
    """
    proxies: list[str] = []
    for token in raw.replace("\n", " ").split():
        token = token.strip()
        if token:
            proxies.append(token)
    return proxies


def _gopass_enabled() -> bool:
    """Whether the gopass fallback is allowed for this process.

    Honors ``PRY_SECRET_BACKEND`` so tests (``env``/``file``) never touch
    the real fleet secret. ``auto`` (the default) and ``gopass`` attempt
    the gopass lookup; ``env``/``file`` skip it.
    """
    backend = os.getenv("PRY_SECRET_BACKEND", "auto").lower()
    return backend not in ("env", "file")


def _load_from_gopass() -> str:
    """Best-effort read of the Webshare proxy list from gopass. Returns "" on any failure."""
    if not _gopass_enabled():
        return ""
    bin_path = shutil.which("gopass")
    if not bin_path:
        return ""
    try:
        result = subprocess.run(  # noqa: S603 - args are constants, not untrusted input
            [bin_path, "show", "-o", WEBSHARE_GOPASS_PATH],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.rstrip("\n")
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.debug("webshare_gopass_read_failed", extra={"error": str(e)[:80]})
    return ""


@lru_cache(maxsize=1)
def _resolve_proxy_list() -> tuple[tuple[str, ...], str]:
    """Resolve (proxies, source) once per process. Cached."""
    raw = os.getenv(WEBSHARE_PROXY_LIST_ENV, "").strip()
    if raw:
        proxies = parse_proxy_list(raw)
        if proxies:
            return tuple(proxies), "env"

    if _gopass_enabled():
        gopass_raw = _load_from_gopass()
        if gopass_raw:
            proxies = parse_proxy_list(gopass_raw)
            if proxies:
                return tuple(proxies), "gopass"

    return (), "none"


def load_webshare_proxies() -> list[str]:
    """Return the cached Webshare proxy pool as a list of proxy URLs."""
    proxies, _ = _resolve_proxy_list()
    return list(proxies)


def webshare_source() -> str:
    """Return where the pool came from: ``env``, ``gopass``, or ``none``."""
    _, source = _resolve_proxy_list()
    return source


def next_webshare_proxy() -> str | None:
    """Return the next proxy in the pool (round-robin), or None if the pool is empty.

    Rotation state is module-level so it advances across ProxyManager
    instances (each request path constructs a fresh ProxyManager).
    """
    global _rotation_index
    proxies = load_webshare_proxies()
    if not proxies:
        return None
    with _rotation_lock:
        proxy = proxies[_rotation_index % len(proxies)]
        _rotation_index += 1
        return proxy


def reset_rotation() -> None:
    """Reset the round-robin index (used by tests)."""
    global _rotation_index
    with _rotation_lock:
        _rotation_index = 0


def clear_cache() -> None:
    """Clear the cached pool (used by tests / config reload)."""
    _resolve_proxy_list.cache_clear()


def mask_proxy_url(url: str) -> str:
    """Return a proxy URL with the password portion redacted.

    ``http://user:pass@host:8080`` -> ``http://user:***@host:8080``.
    URLs without credentials are returned unchanged.
    """
    if "://" not in url:
        return url
    scheme, _, rest = url.partition("://")
    if "@" not in rest:
        return url
    userinfo, _, host = rest.rpartition("@")
    user = userinfo.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"
