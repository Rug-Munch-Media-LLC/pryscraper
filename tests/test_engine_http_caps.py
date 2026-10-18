"""Cross-tier response-size caps and timeouts.

cloudscraper, FlareSolverr, camoufox and Tor must all enforce the single
``MAX_RESPONSE_BYTES`` ceiling and turn a hung transport into a tier failure
(``None``), never an exception that burns the fallback chain.
No network, no real browser — every external edge is faked.
"""

from __future__ import annotations

import asyncio
import json
import sys
import types

from pry.engine import camoufox_integration, flaresolverr, tiers_http, tiers_special, url_guard
from pry.engine.body_limits import MAX_RESPONSE_BYTES, cap_bytes, cap_text

MIB = 1024 * 1024
BIG = b"x" * (6 * MIB)


class _Resp:
    """Streamed httpx/aiohttp response stand-in (also its own async CM)."""

    def __init__(self, body: bytes = BIG) -> None:
        self._body = body
        self.headers = {"content-length": str(len(body))}
        self.status_code = self.status = 200
        self.is_success = True
        self.charset = "utf-8"
        self.content = self
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def aclose(self) -> None:
        self.closed = True

    def raise_for_status(self) -> None:
        return None

    async def iter_chunked(self, n: int = 65536):
        for i in range(0, len(self._body), n):
            yield self._body[i : i + n]

    async def aiter_bytes(self):
        async for chunk in self.iter_chunked():
            yield chunk


class _Client:
    resp: _Resp = _Resp()

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    def stream(self, *args, **kwargs):
        return self.resp


class _HungClient(_Client):
    def stream(self, *args, **kwargs):
        raise TimeoutError("transport hung")


class _CloudScraper:
    body: bytes = BIG
    hang = False

    def get(self, *args, **kwargs):
        if self.hang:
            raise TimeoutError("hung")
        return _CloudResp(self.body)


class _CloudResp:
    status_code = 200
    encoding = "utf-8"

    def __init__(self, body: bytes) -> None:
        self._body = body

    def close(self) -> None:
        return None

    def iter_content(self, chunk_size: int):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]


def _cloud(monkeypatch, *, hang: bool = False) -> None:
    module = types.ModuleType("cloudscraper")
    _CloudScraper.hang = hang
    module.create_scraper = lambda **kwargs: _CloudScraper()
    monkeypatch.setitem(sys.modules, "cloudscraper", module)
    monkeypatch.setattr(tiers_http, "_us_flag", lambda name: True)


class _HTTPTier(tiers_http.TierHTTPMixin):
    def _rotate_ua(self) -> str:
        return "test-agent"


class _SpecialTier(tiers_special.TierSpecialMixin):
    def _build_headers(self, url: str) -> dict[str, str]:
        return {}


def _async(value):
    async def _get():
        return value

    return _get


def test_one_constant_shared_by_every_tier():
    assert MAX_RESPONSE_BYTES == url_guard.MAX_RESPONSE_BYTES
    assert len(cap_bytes(BIG, "https://example.com/")[0]) == MAX_RESPONSE_BYTES
    assert cap_bytes(BIG, "https://example.com/")[1] is True
    assert cap_text("x" * (MAX_RESPONSE_BYTES + 1), "https://example.com/")[1] is True


async def test_cloudscraper_caps_body_and_hung_transport(monkeypatch):
    _cloud(monkeypatch)
    opts: dict[str, object] = {}
    text = await _HTTPTier()._tier_cloudscraper("https://example.com/", opts)
    assert text is not None
    assert len(text) == MAX_RESPONSE_BYTES
    assert opts["pry_truncated"] is True
    _cloud(monkeypatch, hang=True)
    assert await _HTTPTier()._tier_cloudscraper("https://example.com/", {}) is None


async def test_flare_tier_caps_solution_and_hung_transport(monkeypatch):
    body = json.dumps({"solution": {"status": 200, "response": "y" * (6 * MIB)}})
    _Client.resp = _Resp(body.encode())
    monkeypatch.setattr(tiers_http, "_get_shared_client", _async(_Client()))
    monkeypatch.setattr("pry.core.settings.settings.flaresolverr_url", "http://fake/v1")
    opts: dict[str, object] = {}
    text = await _HTTPTier()._tier_flaresolverr("https://example.com/", opts)
    assert text is not None
    assert len(text) == MAX_RESPONSE_BYTES
    assert opts["pry_truncated"] is True
    monkeypatch.setattr(tiers_http, "_get_shared_client", _async(_HungClient()))
    assert await _HTTPTier()._tier_flaresolverr("https://example.com/", {}) is None


async def test_flaresolverr_module_caps_solution_and_hung_transport(monkeypatch):
    body = json.dumps({"solution": {"status": 200, "response": "z" * (6 * MIB)}})
    _Client.resp = _Resp(body.encode())
    monkeypatch.setattr(flaresolverr.httpx, "AsyncClient", _Client)
    text = await flaresolverr.fetch_via_flaresolverr("https://example.com/")
    assert len(text) == MAX_RESPONSE_BYTES
    monkeypatch.setattr(flaresolverr.httpx, "AsyncClient", _HungClient)
    assert await flaresolverr.fetch_via_flaresolverr("https://example.com/") == ""


def _tor(monkeypatch, *, hang: bool = False) -> None:
    class _Session:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc) -> None:
            return None

        def get(self, *args, **kwargs):
            if hang:
                raise TimeoutError("hung")
            return _Resp()

    aiohttp = types.ModuleType("aiohttp")
    aiohttp.ClientSession = _Session
    aiohttp.ClientTimeout = lambda total: total
    socks = types.ModuleType("aiohttp_socks")
    socks.ProxyConnector = types.SimpleNamespace(from_url=lambda url: None)
    monkeypatch.setitem(sys.modules, "aiohttp", aiohttp)
    monkeypatch.setitem(sys.modules, "aiohttp_socks", socks)
    monkeypatch.setattr(tiers_special, "_us_flag", lambda name: True)


async def test_tor_caps_body_and_hung_transport(monkeypatch):
    _tor(monkeypatch)
    opts: dict[str, object] = {}
    text = await _SpecialTier()._tier_tor("https://example.com/", opts)
    assert text is not None
    assert len(text) == MAX_RESPONSE_BYTES
    assert opts["pry_truncated"] is True
    _tor(monkeypatch, hang=True)
    assert await _SpecialTier()._tier_tor("https://example.com/", {}) is None


class _Browser:
    async def new_page(self):
        return _Page()


class _Page:
    async def close(self) -> None:
        return None


async def test_camoufox_caps_content_and_times_out(monkeypatch):
    async def _fake_fetch_page(page, spec, guard):
        return {"success": True, "content": "h" * (6 * MIB), "raw_html": "h"}

    monkeypatch.setattr(camoufox_integration, "_has_camoufox", True)
    monkeypatch.setattr(camoufox_integration, "fetch_page", _fake_fetch_page)
    monkeypatch.setattr(camoufox_integration, "validate_url", lambda url: url)
    result = await camoufox_integration.CamoufoxBrowser().fetch(
        "https://example.com/", browser=_Browser()
    )
    assert len(result["content"]) == MAX_RESPONSE_BYTES
    assert result["truncated"] is True

    async def _hung(page, spec, guard):
        await asyncio.sleep(30)

    monkeypatch.setattr(camoufox_integration, "fetch_page", _hung)
    monkeypatch.setattr(camoufox_integration, "_BROWSER_TIMEOUT_S", 0.01)
    result = await camoufox_integration.CamoufoxBrowser().fetch(
        "https://example.com/", browser=_Browser()
    )
    assert result["success"] is False
