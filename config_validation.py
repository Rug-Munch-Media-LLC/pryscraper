"""Pry — startup configuration validation.

Central, dependency-light validation for the Pry settings object. Call
``validate_config(settings)`` once at process startup (e.g. from the
Docker entrypoint or ``cli.py``) and treat any ``[ERROR]`` entry as
fail-fast: a production instance must not boot with a missing API key on
a public bind, an unusable proxy, or an unparseable rate limit.

The module deliberately does NOT import ``settings`` itself so it can be
unit-tested with plain namespaces / fakes, and so importing it never
triggers the ``PrySettings()`` singleton (which touches the secrets
backend and config file).

Contract
--------
``validate_config(settings) -> list[str]``

Each returned string is prefixed with ``[ERROR]`` or ``[WARNING]``.
An empty list means the configuration is OK.

* ``[ERROR]``   — must be fixed before startup; fail fast.
* ``[WARNING]`` — degraded but bootable; log it.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit

# Hosts/patterns that count as "loopback-only" — an API key is not required
# when the service binds to these. Anything else (0.0.0.0, ::, an internal
# NIC, a public IP) is a remote exposure and requires a key.
_LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost"})

# Scheme prefixes accepted for outbound proxies. socks5h resolves DNS
# through the proxy; socks5/socks4 do not.
_ALLOWED_PROXY_SCHEMES: frozenset[str] = frozenset({"http", "https", "socks4", "socks5", "socks5h"})

# x402 wallet placeholders that mean "not actually configured".
_PLACEHOLDER_WALLETS: frozenset[str] = frozenset({"", "pry-default", "pry-default-wallet"})

# Default facilitator (public x402 facilitator). A custom value is allowed
# as long as it parses as an https URL.
_DEFAULT_FACILITATOR = "https://x402.org/facilitator"

# Sanity bounds for RATE_LIMIT_RPM. 60k RPM is 1k req/s — far beyond any
# realistic single-node scrape workload; anything above is a config bug.
RATE_LIMIT_RPM_MIN = 1
RATE_LIMIT_RPM_MAX = 60_000
RATE_LIMIT_RPM_WARN_ABOVE = 6_000

# SQLAlchemy database URL schemes this app knows how to use.
_ALLOWED_DB_SCHEMES: frozenset[str] = frozenset(
    {"sqlite", "sqlite+aiosqlite", "postgresql", "postgresql+asyncpg", "postgresql+psycopg2"}
)

ERROR_PREFIX = "[ERROR]"
WARNING_PREFIX = "[WARNING]"


def is_loopback_host(host: str) -> bool:
    """Return True when ``host`` binds only to loopback interfaces."""
    host = (host or "").strip().lower()
    return host in _LOOPBACK_HOSTS or host.startswith("127.")


def _as_int(value: Any, name: str) -> int | None:
    """Coerce a settings value to int; return None when unparseable."""
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def _proxy_scheme(url: str) -> str:
    """Return the lower-cased scheme of a proxy URL, or '' when unparseable.

    Requires the ``scheme://`` delimiter: ``proxy.example:8080`` is a
    host:port (no scheme), not a scheme named ``proxy.example``.
    """
    if "://" not in url:
        return ""
    try:
        return urlsplit(url).scheme.lower()
    except ValueError:
        return ""


def _x402_enabled(settings: Any) -> bool:
    """Whether x402 payment gating is switched on.

    x402 has no field on PrySettings (it is env-driven), so we read the
    environment plus any attribute the settings object happens to expose.
    """
    attr = getattr(settings, "x402_enabled", None)
    if attr is not None:
        return bool(attr)
    return _env_flag("PRY_X402_ENABLED")


def _x402_wallet(settings: Any) -> str:
    attr = getattr(settings, "x402_wallet", None)
    if attr:
        return str(attr)
    return os.getenv("PRY_X402_WALLET", "").strip()


def _x402_facilitator(settings: Any) -> str:
    attr = getattr(settings, "x402_facilitator", None)
    if attr:
        return str(attr)
    return os.getenv("PRY_X402_FACILITATOR", _DEFAULT_FACILITATOR).strip()


def validate_config(settings: Any) -> list[str]:
    """Validate a settings object and return a list of issues.

    Each item is a human-readable string prefixed with ``[ERROR]`` or
    ``[WARNING]``. An empty list means the configuration is sound.

    ``settings`` may be a ``PrySettings`` instance or any duck-typed
    object exposing the same attributes (tests use SimpleNamespace).
    """
    issues: list[str] = []

    # ── API key vs. bind address (fail-fast) ─────────────────────────
    host = getattr(settings, "host", "127.0.0.1") or "127.0.0.1"
    api_key = getattr(settings, "api_key", "") or ""
    if not api_key:
        if not is_loopback_host(host):
            issues.append(
                f"{ERROR_PREFIX} PRY_API_KEY is empty but the service binds to "
                f"non-loopback host {host!r}; remote clients would be exposed "
                "without authentication. Set PRY_API_KEY (or bind to 127.0.0.1)."
            )
        else:
            issues.append(
                f"{WARNING_PREFIX} PRY_API_KEY is empty; the API is loopback-only "
                "and remote clients will be rejected with 401. Set PRY_API_KEY "
                "before exposing the service."
            )

    # ── Rate limit (fail-fast on unparseable/absurd values) ──────────
    rpm = _as_int(getattr(settings, "rate_limit_rpm", 120), "rate_limit_rpm")
    if rpm is None:
        issues.append(
            f"{ERROR_PREFIX} PRY_RATE_LIMIT_RPM must be an integer, got "
            f"{getattr(settings, 'rate_limit_rpm', None)!r}."
        )
    elif rpm < RATE_LIMIT_RPM_MIN:
        issues.append(
            f"{ERROR_PREFIX} PRY_RATE_LIMIT_RPM={rpm} is below the minimum of "
            f"{RATE_LIMIT_RPM_MIN}; the rate limiter would reject every request."
        )
    elif rpm > RATE_LIMIT_RPM_MAX:
        issues.append(
            f"{ERROR_PREFIX} PRY_RATE_LIMIT_RPM={rpm} exceeds the maximum of "
            f"{RATE_LIMIT_RPM_MAX}; this is almost certainly a config error."
        )
    elif rpm > RATE_LIMIT_RPM_WARN_ABOVE:
        issues.append(
            f"{WARNING_PREFIX} PRY_RATE_LIMIT_RPM={rpm} is very high "
            f"(>{RATE_LIMIT_RPM_WARN_ABOVE}); verify this is intentional."
        )

    # ── Proxy (fail-fast on unusable URLs) ───────────────────────────
    proxy_url = getattr(settings, "proxy_url", "") or ""
    proxy_enabled = bool(getattr(settings, "proxy_enabled", False))
    if proxy_url:
        scheme = _proxy_scheme(proxy_url)
        if not scheme:
            issues.append(
                f"{ERROR_PREFIX} proxy URL {proxy_url!r} has no scheme; include "
                "http://, https://, socks4://, socks5:// or socks5h://."
            )
        elif scheme not in _ALLOWED_PROXY_SCHEMES:
            issues.append(
                f"{ERROR_PREFIX} proxy URL scheme {scheme!r} is not supported "
                f"(allowed: {', '.join(sorted(_ALLOWED_PROXY_SCHEMES))})."
            )
        elif not proxy_enabled:
            issues.append(
                f"{WARNING_PREFIX} proxy URL is set ({proxy_url!r}) but "
                "PRY_PROXY_ENABLED is false; the proxy will be ignored."
            )
    elif proxy_enabled:
        issues.append(
            f"{WARNING_PREFIX} PRY_PROXY_ENABLED is true but no proxy URL is "
            "configured; scraping will fall back to direct connections."
        )

    # ── x402 (fail-fast when enabled without a real wallet) ──────────
    if _x402_enabled(settings):
        wallet = _x402_wallet(settings)
        if wallet in _PLACEHOLDER_WALLETS:
            issues.append(
                f"{ERROR_PREFIX} x402 is enabled but no wallet is configured. "
                "Set PRY_X402_WALLET (or configure the x402_wallet secret) to "
                "a real receiving address before enabling payments."
            )
        facilitator = _x402_facilitator(settings)
        if facilitator and _proxy_scheme(facilitator) not in ("http", "https"):
            issues.append(
                f"{ERROR_PREFIX} x402 facilitator URL {facilitator!r} is invalid; "
                "it must be an http(s) URL."
            )

    # ── Database / cache URLs (warnings — boot is possible) ──────────
    db_url = getattr(settings, "database_url", "") or ""
    if db_url:
        scheme = db_url.split("://", 1)[0].lower() if "://" in db_url else ""
        if scheme not in _ALLOWED_DB_SCHEMES:
            issues.append(
                f"{WARNING_PREFIX} PRY_DATABASE_URL scheme {scheme!r} is not in "
                f"the supported set ({', '.join(sorted(_ALLOWED_DB_SCHEMES))}); "
                "the app may fail to connect."
            )
    redis_url = getattr(settings, "redis_url", "") or ""
    if redis_url:
        scheme = redis_url.split("://", 1)[0].lower() if "://" in redis_url else ""
        if scheme not in ("redis", "rediss"):
            issues.append(
                f"{WARNING_PREFIX} PRY_REDIS_URL scheme {scheme!r} is not "
                "redis:// or rediss://; the cache layer will not connect."
            )

    # ── Port sanity ──────────────────────────────────────────────────
    port = _as_int(getattr(settings, "port", 8002), "port")
    if port is not None and not (1 <= port <= 65535):
        issues.append(f"{ERROR_PREFIX} PRY_PORT={port} is outside 1-65535.")

    # ── Output bounds (warnings) ─────────────────────────────────────
    max_chars = _as_int(getattr(settings, "max_chars", 100000), "max_chars")
    if max_chars is not None and max_chars <= 0:
        issues.append(
            f"{ERROR_PREFIX} PRY_MAX_CHARS={max_chars} must be positive; "
            "content extraction would be truncated to nothing."
        )

    return issues


def has_errors(issues: list[str]) -> bool:
    """Return True when any issue is a fail-fast ``[ERROR]``."""
    return any(item.startswith(ERROR_PREFIX) for item in issues)


def errors_only(issues: list[str]) -> list[str]:
    """Return just the ``[ERROR]`` issues."""
    return [item for item in issues if item.startswith(ERROR_PREFIX)]


def validate_config_strict(settings: Any) -> list[str]:
    """Validate and raise ``ValueError`` on the first fail-fast error.

    Intended for the Docker entrypoint / CLI startup path where a broken
    configuration must stop the process instead of booting degraded.
    Returns the full issue list when the configuration is OK (or contains
    only warnings).
    """
    issues = validate_config(settings)
    if has_errors(issues):
        raise ValueError("; ".join(errors_only(issues)))
    return issues
