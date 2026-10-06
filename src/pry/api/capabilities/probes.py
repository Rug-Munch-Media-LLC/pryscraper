"""Low-level capability probes and deployment constants."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import importlib
import importlib.util
import logging
import os
import shutil as shutil
import socket
import sys
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)
MOD_PLAYWRIGHT = "playwright"
MOD_CAMOUFOX = "camoufox"
MOD_UNDETECTED = "undetected_chromedriver"
MOD_CURL_CFFI = "curl_cffi"
MOD_TOR_FALLBACK = "tor_fallback"
MOD_AIOHTTP_SOCKS = "aiohttp_socks"
MOD_PYTESSERACT = "pytesseract"
STEALTH_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "engine" / "stealth_scripts"
_BROWSER_PREFIXES = ("chromium", "firefox", "webkit")
_TCP_PROBE_TIMEOUT = 1.0


def _module_import_state(name: str) -> Literal["ok", "broken", "missing"]:
    """Return the import state of ``name``.

    * ``ok`` — the module imports cleanly (a real import, or a test fake
      already present in ``sys.modules``).
    * ``broken`` — the package is installed (find_spec finds it) but importing
      raises (e.g. ``undetected_chromedriver`` on Python 3.12 without a
      distutils shim).
    * ``missing`` — not installed at all.

    Capability detection must never raise, so import failures of any kind are
    folded into a state.
    """
    try:
        importlib.import_module(name)
        return "ok"
    except Exception as e:  # noqa: BLE001 - capability probes fail closed
        # NB: "module" is a reserved LogRecord attribute in stdlib logging —
        # extra={"module": ...} raises KeyError there. Use a safe key.
        logger.debug("module_import_failed", extra={"import_target": name, "error": str(e)[:100]})
        # A failed import caches a partially-initialized module in
        # sys.modules; evict it so later legitimate imports retry cleanly
        # instead of inheriting the broken half-state.
        sys.modules.pop(name, None)
    try:
        return "broken" if importlib.util.find_spec(name) is not None else "missing"
    except Exception:
        logger.warning("probes_exception_handler", exc_info=True)
        return "missing"


def _playwright_cache_dir() -> Path:
    """Resolve the Playwright browser cache directory.

    Honors ``PLAYWRIGHT_BROWSERS_PATH``; defaults to the standard
    ``~/.cache/ms-playwright`` location.
    """
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env:
        return Path(env)
    return Path.home() / ".cache" / "ms-playwright"


def _playwright_browser_installs() -> list[str]:
    """Return the names of installed Playwright browser builds (best-effort)."""
    cache = _playwright_cache_dir()
    if not cache.is_dir():
        return []
    try:
        return sorted(
            entry.name
            for entry in cache.iterdir()
            if entry.is_dir() and entry.name.startswith(_BROWSER_PREFIXES)
        )
    except OSError:
        logger.warning("probes_exception_handler", exc_info=True)
        return []


def _stealth_scripts_present() -> bool:
    """True when the stealth_scripts directory contains at least one payload."""
    if not STEALTH_SCRIPTS_DIR.is_dir():
        return False
    try:
        return any(STEALTH_SCRIPTS_DIR.glob("*.js"))
    except OSError:
        logger.warning("probes_exception_handler", exc_info=True)
        return False


def _tcp_reachable(host: str, port: int, timeout: float = _TCP_PROBE_TIMEOUT) -> bool:
    """Best-effort TCP reachability probe (DNS errors included via OSError)."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        logger.warning("probes_exception_handler", exc_info=True)
        return False
