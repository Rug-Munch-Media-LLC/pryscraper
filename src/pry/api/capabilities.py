"""Pry — Deployment capability detection.

``detect_capabilities()`` returns a structured report of what this deployment
actually supports (browsers, anti-bot tooling, Tor, proxies, CAPTCHA solving,
LLM providers, storage) plus actionable ``recommendations`` so Pry can
self-configure instead of silently degrading.

Design rules:

* Every check is non-fatal — a failure (missing import, unreachable port,
  unreadable directory) marks the capability unavailable instead of raising.
* Imports are probed lazily and by name, so the module can be imported even
  when optional packages (playwright, camoufox, curl_cffi, ...) are absent.
* Secrets are never exposed: proxy credentials, CAPTCHA API keys and LLM keys
  only contribute booleans / provider tags, never values.
* Storage reachability is a best-effort TCP connect with a short timeout —
  no database clients are launched.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import importlib
import importlib.util
import inspect
import logging
import os
import shutil
import socket
import sys
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pry.core.settings import settings

logger = logging.getLogger(__name__)

# Module names probed by capability detection. Kept at module level so tests
# can inject fakes into ``sys.modules`` by name.
MOD_PLAYWRIGHT = "playwright"
MOD_CAMOUFOX = "camoufox"
MOD_UNDETECTED = "undetected_chromedriver"
MOD_CURL_CFFI = "curl_cffi"
MOD_TOR_FALLBACK = "tor_fallback"
MOD_AIOHTTP_SOCKS = "aiohttp_socks"
MOD_PYTESSERACT = "pytesseract"

# Directory holding the stealth JS payloads shipped with Pry.
STEALTH_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "engine" / "stealth_scripts"

# Playwright cache directory entry prefixes that identify installed browsers
# (e.g. ``chromium-1234``, ``firefox-1420``, ``webkit-2020``).
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
    except Exception as e:
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
        return []


def _stealth_scripts_present() -> bool:
    """True when the stealth_scripts directory contains at least one payload."""
    if not STEALTH_SCRIPTS_DIR.is_dir():
        return False
    try:
        return any(STEALTH_SCRIPTS_DIR.glob("*.js"))
    except OSError:
        return False


def _tcp_reachable(host: str, port: int, timeout: float = _TCP_PROBE_TIMEOUT) -> bool:
    """Best-effort TCP reachability probe (DNS errors included via OSError)."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _browser_capability() -> tuple[bool, str, list[str]]:
    """Detect installed browser automation engines."""
    pw = _module_import_state(MOD_PLAYWRIGHT)
    installs = _playwright_browser_installs()
    camou = _module_import_state(MOD_CAMOUFOX)
    uc = _module_import_state(MOD_UNDETECTED)

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
    tls = _module_import_state(MOD_CURL_CFFI)
    stealth = _stealth_scripts_present()

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
        return importlib.import_module(MOD_TOR_FALLBACK)
    except ImportError:
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
            except Exception as e:
                logger.debug("tor_available() raised", extra={"error": str(e)[:100]})

    socks = _module_import_state(MOD_AIOHTTP_SOCKS)
    if socks == "ok" and _tcp_reachable(settings.tor_socks5_host, settings.tor_socks5_port):
        return True, "aiohttp_socks installed; SOCKS port reachable", []
    if socks == "ok":
        recs.append(
            f"start tor and set PRY_TOR_ENABLED=true "
            f"(SOCKS {settings.tor_socks5_host}:{settings.tor_socks5_port} unreachable)"
        )
    else:
        recs.append("pip install aiohttp-socks, or install tor + set PRY_TOR_ENABLED=true")
    return False, "no reachable tor SOCKS proxy", recs


def _proxy_capability() -> tuple[bool, str, list[str]]:
    """Detect whether egress is routed through a proxy.

    Reports a boolean plus a provider tag only — never the proxy URL or any
    credential material.
    """
    if settings.tor_enabled:
        return True, "tor", []
    if settings.proxy_enabled and settings.proxy_url:
        return True, settings.proxy_type or "http", []
    try:
        from pry.engine.proxy_manager import ProxyManager

        manager = ProxyManager()
        if manager.get_proxy_url() and manager.active_config.provider != "free":
            return True, manager.active_config.provider, []
    except Exception:
        logger.debug("proxy manager probe failed", exc_info=True)
    return False, "none", ["set PRY_PROXY_ENABLED=true and PRY_PROXY_URL to route through a proxy"]


def _captcha_capability() -> tuple[bool, str, list[str]]:
    """Detect CAPTCHA solving backends (OCR and/or paid token APIs).

    API keys contribute booleans only — values are never exposed.
    """
    recs: list[str] = []
    ocr_pkg = _module_import_state(MOD_PYTESSERACT) == "ok"
    ocr_bin = shutil.which("tesseract") is not None
    ocr_ready = ocr_pkg and ocr_bin

    api_keys = [
        name
        for name, key in (
            ("2captcha", settings.captcha_2captcha_api_key),
            ("capsolver", settings.captcha_capsolver_api_key),
        )
        if key
    ]

    parts: list[str] = []
    if ocr_ready:
        parts.append("local OCR (pytesseract + tesseract)")
    elif ocr_pkg or ocr_bin:
        parts.append("incomplete OCR: pytesseract and the tesseract binary are both required")
        if ocr_pkg and not ocr_bin:
            recs.append("install the tesseract binary (apt-get install tesseract-ocr)")
        else:
            recs.append("pip install pytesseract")
    else:
        recs.append("install tesseract-ocr and pip install pytesseract for local OCR")

    if api_keys:
        parts.append("API keys: " + ", ".join(api_keys))
    else:
        recs.append(
            "set PRY_CAPTCHA_2CAPTCHA_API_KEY or PRY_CAPTCHA_CAPSOLVER_API_KEY "
            "for paid CAPTCHA solving"
        )

    return ocr_ready or bool(api_keys), "; ".join(parts), recs


def _llm_capability() -> tuple[bool, str, list[str]]:
    """Detect whether an LLM API key is configured (booleans/provider names only)."""
    providers = [
        name
        for name, key in (
            ("openrouter", settings.openrouter_api_key),
            ("openai", settings.openai_api_key),
            ("anthropic", settings.anthropic_api_key),
            ("cohere", settings.cohere_api_key),
        )
        if key
    ]
    if providers:
        return True, ", ".join(providers), []
    return (
        False,
        "no LLM API key configured",
        [
            "set PRY_OPENROUTER_API_KEY (or PRY_OPENAI_API_KEY / PRY_ANTHROPIC_API_KEY / "
            "PRY_COHERE_API_KEY) to enable LLM features"
        ],
    )


def _default_db_port(scheme: str) -> int:
    """Best-effort default TCP port for common DB URL schemes."""
    if "mysql" in scheme:
        return 3306
    if "mssql" in scheme:
        return 1433
    if "oracle" in scheme:
        return 1521
    return 5432  # postgres and everything else


def _db_capability() -> tuple[bool, str]:
    """Best-effort Postgres/DB reachability via a short TCP probe (non-fatal)."""
    url = settings.database_url
    if not url:
        return False, "no database_url configured"
    if url.startswith("sqlite"):
        try:
            path = urlsplit(url).path
            present = bool(path) and Path(path).exists()
            return present, f"sqlite database file {'present' if present else 'missing'}"
        except Exception:
            return False, "sqlite database unavailable"
    parts = urlsplit(url)
    host = parts.hostname or "localhost"
    try:
        port = parts.port
    except ValueError:
        port = None
    port = port or _default_db_port(parts.scheme)
    if _tcp_reachable(host, port):
        return True, f"{parts.scheme} reachable at {host}:{port}"
    return False, f"{parts.scheme} not reachable at {host}:{port}"


def _redis_capability() -> tuple[bool, str]:
    """Best-effort Redis reachability via a short TCP probe (non-fatal)."""
    url = settings.redis_url
    if not url:
        return False, "no redis_url configured"
    parts = urlsplit(url)
    host = parts.hostname or "localhost"
    try:
        port = parts.port
    except ValueError:
        port = None
    port = port or 6379
    if _tcp_reachable(host, port):
        return True, f"redis reachable at {host}:{port}"
    return False, f"redis not reachable at {host}:{port}"


def _storage_capability() -> tuple[bool, str, list[str]]:
    """Detect DB + Redis reachability (lazy, best-effort, non-fatal)."""
    db_ok, db_detail = _db_capability()
    redis_ok, redis_detail = _redis_capability()
    recs: list[str] = []
    if not db_ok:
        recs.append("start Postgres and check PRY_DATABASE_URL")
    if not redis_ok:
        recs.append("start Redis and check PRY_REDIS_URL")
    return db_ok and redis_ok, f"db: {db_detail}; redis: {redis_detail}", recs


def detect_capabilities() -> dict[str, Any]:
    """Return a structured report of what this deployment actually supports.

    Every entry is ``{"available": bool, "detail": str}``; the report also
    carries a ``recommendations`` list of actionable strings (no secrets).
    """
    sections: dict[str, Any] = {}
    recommendations: list[str] = []
    for name, detector in (
        ("browsers", _browser_capability),
        ("anti_bot", _anti_bot_capability),
        ("tor", _tor_capability),
        ("proxies", _proxy_capability),
        ("captcha", _captcha_capability),
        ("llm", _llm_capability),
        ("storage", _storage_capability),
    ):
        available, detail, recs = detector()
        sections[name] = {"available": available, "detail": detail}
        recommendations.extend(recs)

    sections["recommendations"] = recommendations
    return sections
