"""Stable deployment capability detection facade."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from pry.api.capabilities import probes as probes, runtime as runtime
from pry.api.capabilities.detector import detect_capabilities
from pry.api.capabilities.probes import (
    MOD_AIOHTTP_SOCKS,
    MOD_CAMOUFOX,
    MOD_CURL_CFFI,
    MOD_PLAYWRIGHT,
    MOD_PYTESSERACT,
    MOD_TOR_FALLBACK,
    MOD_UNDETECTED,
    STEALTH_SCRIPTS_DIR,
    _module_import_state,
    _playwright_browser_installs,
    _playwright_cache_dir,
    _stealth_scripts_present,
    _tcp_reachable,
)
from pry.api.capabilities.runtime import (
    _anti_bot_capability,
    _browser_capability,
    _import_tor_fallback,
    _tor_capability,
)
from pry.api.capabilities.services import (
    _captcha_capability,
    _llm_capability,
    _proxy_capability,
)
from pry.api.capabilities.storage import (
    _db_capability,
    _default_db_port,
    _redis_capability,
    _storage_capability,
)

__all__ = [
    "MOD_AIOHTTP_SOCKS",
    "MOD_CAMOUFOX",
    "MOD_CURL_CFFI",
    "MOD_PLAYWRIGHT",
    "MOD_PYTESSERACT",
    "MOD_TOR_FALLBACK",
    "MOD_UNDETECTED",
    "STEALTH_SCRIPTS_DIR",
    "_anti_bot_capability",
    "_browser_capability",
    "_captcha_capability",
    "_db_capability",
    "_default_db_port",
    "_import_tor_fallback",
    "_llm_capability",
    "_module_import_state",
    "_playwright_browser_installs",
    "_playwright_cache_dir",
    "_proxy_capability",
    "_redis_capability",
    "_stealth_scripts_present",
    "_storage_capability",
    "_tcp_reachable",
    "_tor_capability",
    "detect_capabilities",
    "probes",
    "runtime",
]
