# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for deployment capability detection (capabilities.py + router).

Mock optional imports, system binaries, settings, and TCP probes so capability
reports stay deterministic; secrets are checked only by boolean/provider tags.
"""

from __future__ import annotations

import json
import sys
import types
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from pry.api import capabilities
from pry.api.routers.core.capabilities import router as capabilities_router
from pry.core.settings import settings
from tests.env_isolation import no_llm_keys, only_openrouter_llm

if TYPE_CHECKING:
    from pathlib import Path


def _fake_module(monkeypatch: pytest.MonkeyPatch, name: str) -> types.ModuleType:
    """Register a fake module in sys.modules (auto-restored after the test)."""
    mod = types.ModuleType(name)
    monkeypatch.setitem(sys.modules, name, mod)
    return mod


@pytest.fixture(autouse=True)
def _fast_tcp_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default: TCP probes never touch the network unless a test opts in."""
    monkeypatch.setattr(
        capabilities.probes, "_tcp_reachable", lambda host, port, timeout=1.0: False
    )


def test_detect_all_available(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Everything present: all sections available and no recommendations."""
    for name in (
        capabilities.MOD_PLAYWRIGHT,
        capabilities.MOD_CAMOUFOX,
        capabilities.MOD_UNDETECTED,
        capabilities.MOD_CURL_CFFI,
        capabilities.MOD_AIOHTTP_SOCKS,
        capabilities.MOD_PYTESSERACT,
    ):
        _fake_module(monkeypatch, name)

    tor_fallback = _fake_module(monkeypatch, capabilities.MOD_TOR_FALLBACK)
    tor_fallback.tor_available = lambda: True  # type: ignore[attr-defined]

    browser_dir = tmp_path / "browsers"
    browser_dir.mkdir()
    (browser_dir / "chromium-1234").mkdir()
    (browser_dir / "firefox-1420").mkdir()
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(browser_dir))

    monkeypatch.setattr(
        capabilities.probes.shutil,
        "which",
        lambda name: "/usr/bin/tesseract" if name == "tesseract" else None,
    )
    monkeypatch.setattr(settings, "proxy_enabled", True)
    monkeypatch.setattr(settings, "proxy_url", "http://proxy.example:8080")
    monkeypatch.setattr(settings, "proxy_type", "http")
    monkeypatch.setattr(settings, "captcha_2captcha_api_key", "fake-key-2captcha")
    monkeypatch.setattr(settings, "captcha_capsolver_api_key", "fake-key-capsolver")
    only_openrouter_llm(monkeypatch)
    monkeypatch.setattr(capabilities.probes, "_tcp_reachable", lambda host, port, timeout=1.0: True)

    report = capabilities.detect_capabilities()

    assert report["browsers"]["available"] is True
    assert "playwright" in report["browsers"]["detail"]
    assert "chromium-1234" in report["browsers"]["detail"]
    assert report["anti_bot"]["available"] is True
    assert "curl_cffi" in report["anti_bot"]["detail"]
    assert "stealth scripts present" in report["anti_bot"]["detail"]
    assert report["tor"]["available"] is True
    assert report["tor"]["detail"] == "tor_fallback.tor_available()"
    assert report["proxies"]["available"] is True
    assert report["proxies"]["detail"] == "http"
    assert report["captcha"]["available"] is True
    assert "local OCR" in report["captcha"]["detail"]
    assert "2captcha" in report["captcha"]["detail"]
    assert report["llm"]["available"] is True
    assert report["llm"]["detail"] == "openrouter"
    assert report["storage"]["available"] is True
    assert "db:" in report["storage"]["detail"]
    assert report["recommendations"] == []


def test_detect_all_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Nothing present: all sections unavailable with actionable recommendations."""
    monkeypatch.setattr(capabilities.probes, "_module_import_state", lambda name: "missing")
    monkeypatch.setattr(capabilities.runtime, "_import_tor_fallback", lambda: None)
    monkeypatch.setattr(capabilities.probes, "STEALTH_SCRIPTS_DIR", tmp_path / "no_scripts")
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.setattr(capabilities.probes.shutil, "which", lambda name: None)
    monkeypatch.setattr(settings, "tor_enabled", False)
    monkeypatch.setattr(settings, "proxy_enabled", False)
    monkeypatch.setattr(settings, "proxy_url", "")
    monkeypatch.setattr(settings, "captcha_2captcha_api_key", "")
    monkeypatch.setattr(settings, "captcha_capsolver_api_key", "")
    no_llm_keys(monkeypatch)
    monkeypatch.setattr(
        capabilities.probes, "_tcp_reachable", lambda host, port, timeout=1.0: False
    )

    report = capabilities.detect_capabilities()

    assert report["browsers"]["available"] is False
    assert "not installed" in report["browsers"]["detail"]
    assert report["anti_bot"]["available"] is False
    assert "stealth scripts missing" in report["anti_bot"]["detail"]
    assert report["tor"]["available"] is False
    assert report["proxies"]["available"] is False
    assert report["proxies"]["detail"] == "none"
    assert report["captcha"]["available"] is False
    assert report["llm"]["available"] is False
    assert report["storage"]["available"] is False

    recs = " | ".join(report["recommendations"])
    assert "pip install playwright" in recs
    assert "pip install camoufox" in recs
    assert "pip install undetected-chromedriver" in recs
    assert "pip install curl_cffi" in recs
    assert "install tor + set PRY_TOR_ENABLED=true" in recs
    assert "PRY_PROXY_ENABLED=true" in recs
    assert "tesseract-ocr" in recs
    assert "PRY_CAPTCHA_2CAPTCHA_API_KEY" in recs
    assert "PRY_OPENROUTER_API_KEY" in recs
    assert "start Postgres" in recs
    assert "start Redis" in recs


def test_module_import_state_ok_and_missing() -> None:
    """Real import path: installed module -> ok, unknown module -> missing."""
    assert capabilities.probes._module_import_state("playwright") == "ok"
    assert capabilities.probes._module_import_state("pry_no_such_module_xyz_987") == "missing"


def test_module_import_state_broken_real_world() -> None:
    """undetected-chromedriver is installed but broken without distutils on 3.12."""
    import importlib.util

    if importlib.util.find_spec(capabilities.MOD_UNDETECTED) is None:
        pytest.skip("undetected-chromedriver not installed in this environment")
    state = capabilities.probes._module_import_state(capabilities.MOD_UNDETECTED)
    assert state in ("ok", "broken")
    if state == "broken":
        assert "distutils" in capabilities._browser_capability()[2][-1]


def test_tor_fallback_async_falls_back_to_socks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An async tor_available() is skipped; the SOCKS probe decides instead."""
    tor_fallback = _fake_module(monkeypatch, capabilities.MOD_TOR_FALLBACK)

    async def tor_available() -> bool:
        return True

    tor_fallback.tor_available = tor_available  # type: ignore[attr-defined]
    _fake_module(monkeypatch, capabilities.MOD_AIOHTTP_SOCKS)
    monkeypatch.setattr(
        capabilities.probes, "_tcp_reachable", lambda host, port, timeout=1.0: False
    )

    available, detail, recs = capabilities._tor_capability()
    assert available is False
    assert "no reachable tor SOCKS proxy" in detail
    assert any("start tor" in rec for rec in recs)


def test_no_secrets_leak_into_report(monkeypatch: pytest.MonkeyPatch) -> None:
    """Secret values must never appear anywhere in the report."""
    _fake_module(monkeypatch, capabilities.MOD_PYTESSERACT)
    monkeypatch.setattr(
        capabilities.probes.shutil,
        "which",
        lambda name: "/usr/bin/tesseract" if name == "tesseract" else None,
    )
    monkeypatch.setattr(settings, "proxy_enabled", True)
    monkeypatch.setattr(settings, "proxy_url", "http://proxyuser:proxypa55@proxy.example:8080")
    monkeypatch.setattr(settings, "proxy_type", "socks5")
    monkeypatch.setattr(settings, "captcha_2captcha_api_key", "2captcha-super-secret")
    only_openrouter_llm(monkeypatch, key="openrouter-super-secret")
    monkeypatch.setattr(capabilities.probes, "_tcp_reachable", lambda host, port, timeout=1.0: True)

    report = capabilities.detect_capabilities()
    serialized = json.dumps(report)

    assert "proxypa55" not in serialized
    assert "proxyuser" not in serialized
    assert "2captcha-super-secret" not in serialized
    assert "openrouter-super-secret" not in serialized


def test_storage_sqlite_database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """SQLite URLs are probed by file presence instead of TCP."""
    monkeypatch.setattr(settings, "database_url", "sqlite:///nonexistent-pry.db")
    available, detail = capabilities._db_capability()
    assert available is False
    assert "missing" in detail

    db_file = tmp_path / "pry.db"
    db_file.write_text("sqlite file")
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{db_file}")
    available, detail = capabilities._db_capability()
    assert available is True
    assert "present" in detail


def test_capabilities_router_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /v1/capabilities returns the structured report.

    The router is not wired into ``api.py`` yet (lead wires it), so it is
    tested standalone via a minimal app — the repo pattern used by
    tests/test_signup_automation.py for unwired routers.
    """
    from fastapi import FastAPI

    monkeypatch.setattr(
        capabilities.probes, "_tcp_reachable", lambda host, port, timeout=1.0: False
    )
    app = FastAPI()
    app.include_router(capabilities_router)
    client = TestClient(app)
    response = client.get("/v1/capabilities")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    data = payload["data"]
    for key in (
        "browsers",
        "anti_bot",
        "tor",
        "proxies",
        "captcha",
        "llm",
        "storage",
        "recommendations",
    ):
        assert key in data
    for key in ("browsers", "anti_bot", "tor", "proxies", "captcha", "llm", "storage"):
        assert set(data[key]) == {"available", "detail"}
    assert isinstance(data["recommendations"], list)
