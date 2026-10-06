"""Browser, anti-bot, Tor, and stealth capability detection."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import importlib
import inspect
import logging
from typing import Any

from pry.api.capabilities import probes
from pry.core.settings import settings

logger = logging.getLogger(__name__)


def _browser_capability() -> tuple[bool, str, list[str]]:
    """Detect installed browser automation engines."""
    pw = probes._module_import_state(probes.MOD_PLAYWRIGHT)
    installs = probes._playwright_browser_installs()
    camou = probes._module_import_state(probes.MOD_CAMOUFOX)
    uc = probes._module_import_state(probes.MOD_UNDETECTED)

    parts: list[str] = []
    recs: list[str] = []
    if pw == "ok":
        if installs:
            parts.append(f"playwright (browsers: {', '.join(installs)})")
        else:
            parts.append("playwright (import OK, no browsers installed)")
            recs.append("run: playwright install chromium")
    elif pw == "broken":
        parts.append("playwright (installed but import fails)")
        recs.append("fix playwright install (pip check playwright)")
    else:
        parts.append("playwright (not installed)")
        recs.append("pip install playwright")

    if camou == "ok":
        parts.append("camoufox")
    elif camou == "broken":
        parts.append("camoufox (installed but import fails)")
        recs.append("fix camoufox install (pip check camoufox)")
    else:
        parts.append("camoufox (not installed)")
        recs.append("pip install camoufox && python -m camoufox fetch")

    if uc == "ok":
        parts.append("undetected-chromedriver")
    elif uc == "broken":
        parts.append("undetected-chromedriver (installed but import fails)")
        recs.append(
            "undetected-chromedriver import fails on Python 3.12 without a distutils "
            "shim: pip install setuptools"
        )
    else:
        parts.append("undetected-chromedriver (not installed)")
        recs.append("pip install undetected-chromedriver")

    available = (pw == "ok" and bool(installs)) or camou == "ok" or uc == "ok"
    return available, "; ".join(parts), recs


def _anti_bot_capability() -> tuple[bool, str, list[str]]:
    """Detect TLS fingerprinting and stealth-script anti-bot tooling."""
    tls = probes._module_import_state(probes.MOD_CURL_CFFI)
    stealth = probes._stealth_scripts_present()

    parts: list[str] = []
    recs: list[str] = []
    if tls == "ok":
        parts.append("tls fingerprinting (curl_cffi)")
    elif tls == "broken":
        parts.append("curl_cffi (installed but import fails)")
        recs.append("fix curl_cffi install (pip check curl_cffi)")
    else:
        parts.append("tls fingerprinting (curl_cffi not installed)")
        recs.append("pip install curl_cffi")

    if stealth:
        parts.append("stealth scripts present")
    else:
        parts.append("stealth scripts missing")
        recs.append("stealth_scripts/ directory is empty — restore the stealth scripts")

    return tls == "ok" or stealth, "; ".join(parts), recs


def _import_tor_fallback() -> Any | None:
    """Guarded import of the optional tor_fallback module (may not exist)."""
    try:
        return importlib.import_module(probes.MOD_TOR_FALLBACK)
    except ImportError:
        logger.warning("runtime_exception_handler", exc_info=True)
        return None


def _tor_capability() -> tuple[bool, str, list[str]]:
    """Detect Tor availability: tor_fallback helper, else SOCKS port probe.

    The ``tor_fallback`` module is optional and may not exist in every
    deployment — the import is guarded. When it is absent (or its
    ``tor_available()`` helper is async/unavailable), fall back to
    ``aiohttp_socks`` presence plus a reachable SOCKS port.
    """
    recs: list[str] = []
    mod = _import_tor_fallback()

    if mod is not None:
        fn = getattr(mod, "tor_available", None)
        if fn is not None and callable(fn) and not inspect.iscoroutinefunction(fn):
            try:
                result = fn()
                if isinstance(result, bool):
                    return result, "tor_fallback.tor_available()", []
            except Exception as e:  # noqa: BLE001 - capability probes fail closed
                logger.debug("tor_available() raised", extra={"error": str(e)[:100]})

    socks = probes._module_import_state(probes.MOD_AIOHTTP_SOCKS)
    if socks == "ok" and probes._tcp_reachable(settings.tor_socks5_host, settings.tor_socks5_port):
        return True, "aiohttp_socks installed; SOCKS port reachable", []
    if socks == "ok":
        recs.append(
            f"start tor and set PRY_TOR_ENABLED=true "
            f"(SOCKS {settings.tor_socks5_host}:{settings.tor_socks5_port} unreachable)"
        )
    else:
        recs.append("pip install aiohttp-socks, or install tor + set PRY_TOR_ENABLED=true")
    return False, "no reachable tor SOCKS proxy", recs
