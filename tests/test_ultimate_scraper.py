# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for ultimate_scraper.py — multi-strategy anti-detection scraper."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

from pry.engine.ultimate_scraper import UltimateScraper, _browser_pool

_VALID_HTML = "<html><body>" + "x" * 600 + "</body></html>"
_VALID_HTML_2 = "<html><body>" + "y" * 600 + "</body></html>"
_VALID_HTML_3 = "<html><body>" + "z" * 600 + "</body></html>"


@pytest.fixture
def scraper() -> UltimateScraper:
    """Return a scraper with a clean registry mock so test pollution is impossible."""
    # Reset the module-level browser pool so a mocked driver/browser cached by
    # one test cannot leak into the next (the pool is a lazy singleton).
    _browser_pool.reset()
    with (
        patch(
            "pry.engine.ultimate_scraper.registry.reorder_for_domain", side_effect=lambda _d, c: c
        ),
        patch("pry.engine.ultimate_scraper.registry.is_service_allowed", return_value=True),
        patch("pry.engine.ultimate_scraper.registry.record_domain_tier_result"),
        patch("pry.engine.ultimate_scraper.registry.record_service_result"),
    ):
        yield UltimateScraper()


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


def test_scraper_init(scraper: UltimateScraper):
    assert scraper is not None
    for t in ["_tier_direct", "_tier_tor", "_tier_archive", "_tier_google_cache"]:
        assert hasattr(scraper, t)


def test_scraper_has_all_tiers(scraper: UltimateScraper):
    tiers = [
        "_tier_direct",
        "_tier_premium_proxy",
        "_tier_cloudscraper",
        "_tier_flaresolverr",
        "_tier_undetected",
        "_tier_playwright",
        "_tier_tls_fingerprint",
        "_tier_camoufox",
        "_tier_googlebot",
        "_tier_archive",
        "_tier_google_cache",
        "_tier_tor",
    ]
    for t in tiers:
        assert hasattr(scraper, t), f"Missing tier: {t}"


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scrape_invalid_url_returns_error(scraper: UltimateScraper):
    result = await scraper.scrape("not-a-url")
    assert result["status"] == "error"


# ---------------------------------------------------------------------------
# UA rotation
# ---------------------------------------------------------------------------


def test_rotate_ua_returns_string(scraper: UltimateScraper):
    ua = scraper._rotate_ua()
    assert isinstance(ua, str)
    assert len(ua) > 20


def test_rotate_ua_changes(scraper: UltimateScraper):
    uas = {scraper._rotate_ua() for _ in range(5)}
    assert len(uas) > 1


# ---------------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------------


def test_build_headers_contains_required(scraper: UltimateScraper):
    h = scraper._build_headers("http://example.com")
    for k in ["User-Agent", "Accept", "Accept-Language"]:
        assert k in h


# ---------------------------------------------------------------------------
# _is_valid
# ---------------------------------------------------------------------------


def test_is_valid_none(scraper: UltimateScraper):
    assert scraper._is_valid(None) is False


def test_is_valid_empty(scraper: UltimateScraper):
    assert scraper._is_valid("") is False


def test_is_valid_short(scraper: UltimateScraper):
    assert scraper._is_valid("ab" * 100) is False


def test_is_valid_ok(scraper: UltimateScraper):
    assert scraper._is_valid(_VALID_HTML) is True


def test_is_valid_body_text_too_short(scraper: UltimateScraper):
    body = "<body>" + "x" * 40 + "</body>"
    assert scraper._is_valid(body) is False


# ---------------------------------------------------------------------------
# _result
# ---------------------------------------------------------------------------


def test_result_success_format(scraper: UltimateScraper):
    result = scraper._result("http://example.com", _VALID_HTML, "direct")
    assert result["status"] == "ok"
    assert result["url"] == "http://example.com"
    assert result["method"] == "direct"
    assert "raw_html" in result


def test_result_contains_block_signal(scraper: UltimateScraper):
    result = scraper._result(
        "http://example.com",
        _VALID_HTML,
        "direct",
        block_signal={"kind": "captcha", "confidence": 0.8},
    )
    assert result["block_signal"]["kind"] == "captcha"


# ---------------------------------------------------------------------------
# Proxy resolution
# ---------------------------------------------------------------------------


def test_resolve_proxy_url_from_opts(scraper: UltimateScraper):
    url = scraper._resolve_proxy_url({"proxy_url": "http://proxy:8080"})
    assert url == "http://proxy:8080"


def test_resolve_proxy_url_none(scraper: UltimateScraper):
    assert scraper._resolve_proxy_url({}) is None


# ---------------------------------------------------------------------------
# scrape — fallback chain
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scrape_direct_success(scraper: UltimateScraper):
    with patch.object(scraper, "_tier_direct", new=AsyncMock(return_value=_VALID_HTML)):
        result = await scraper.scrape("http://example.com")
        assert result["status"] == "ok"
        assert result["method"] == "direct"


@pytest.mark.asyncio
async def test_scrape_all_tiers_fail(scraper: UltimateScraper):
    for t in [
        "_tier_direct",
        "_tier_tls_fingerprint",
        "_tier_cloudscraper",
        "_tier_flaresolverr",
        "_tier_undetected",
        "_tier_camoufox",
        "_tier_playwright",
        "_tier_googlebot",
        "_tier_tor",
        "_tier_archive",
        "_tier_google_cache",
    ]:
        if hasattr(scraper, t):
            setattr(scraper, t, AsyncMock(return_value=None))
    result = await scraper.scrape("http://example.com")
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_scrape_second_tier_works(scraper: UltimateScraper):
    scraper._tier_direct = AsyncMock(return_value=None)
    scraper._tier_tls_fingerprint = AsyncMock(return_value=_VALID_HTML_2)
    result = await scraper.scrape("http://example.com")
    assert result["status"] == "ok"
    assert "tls" in result.get("method", "")


@pytest.mark.asyncio
async def test_scrape_archive_fallback(scraper: UltimateScraper):
    for t in [
        "_tier_direct",
        "_tier_tls_fingerprint",
        "_tier_cloudscraper",
        "_tier_flaresolverr",
        "_tier_undetected",
        "_tier_camoufox",
        "_tier_playwright",
        "_tier_googlebot",
        "_tier_tor",
    ]:
        if hasattr(scraper, t):
            setattr(scraper, t, AsyncMock(return_value=None))
    scraper._tier_archive = AsyncMock(return_value=_VALID_HTML_3)
    scraper._tier_google_cache = AsyncMock(return_value=None)
    result = await scraper.scrape("http://example.com")
    assert result["status"] == "ok"
    assert result["method"] == "archive"


# ---------------------------------------------------------------------------
# Tier exception handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scrape_tier_exception_handled(scraper: UltimateScraper):
    scraper._tier_direct = AsyncMock(side_effect=RuntimeError("boom"))
    scraper._tier_tls_fingerprint = AsyncMock(return_value=_VALID_HTML)
    result = await scraper.scrape("http://example.com")
    assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------


def test_record_telemetry_noop(scraper: UltimateScraper):
    with patch("pry.engine.ultimate_scraper._HAS_FALLBACK_TELEMETRY", False):
        scraper._record_telemetry("example.com", ["direct"], [], "direct", True, 0.0, [])


# ---------------------------------------------------------------------------
# _signal_to_dict
# ---------------------------------------------------------------------------


def test_signal_to_dict(scraper: UltimateScraper):
    signal = MagicMock(
        kind="captcha", confidence=0.95, recommended_escalation="playwright", evidence=set()
    )
    d = scraper._signal_to_dict(signal)
    assert d["kind"] == "captcha"
    assert d["confidence"] == 0.95


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scrape_with_retry(scraper: UltimateScraper):
    scraper._tier_direct = AsyncMock(return_value=_VALID_HTML)
    result = await scraper.scrape("http://example.com", options={"retry": {"max_attempts": 2}})
    assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# _tier_direct — HTTP direct fetch (via respx)
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_tier_direct_success(scraper: UltimateScraper, resolved_dns: str):
    respx.get(f"http://{resolved_dns}/").mock(return_value=httpx.Response(200, text="<html>OK</html>"))
    result = await scraper._tier_direct("http://example.com", {})
    assert result == "<html>OK</html>"


@respx.mock
@pytest.mark.asyncio
async def test_tier_direct_http_error(scraper: UltimateScraper, resolved_dns: str):
    respx.get(f"http://{resolved_dns}/").mock(side_effect=httpx.ConnectError("conn failed"))
    result = await scraper._tier_direct("http://example.com", {})
    assert result is None


# ---------------------------------------------------------------------------
# _tier_premium_proxy
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_tier_premium_proxy_success(scraper: UltimateScraper, resolved_dns: str):
    respx.get(f"http://{resolved_dns}/").mock(
        return_value=httpx.Response(200, text="<html>proxied</html>")
    )
    result = await scraper._tier_premium_proxy("http://example.com", "http://proxy:8080", {})
    assert result == "<html>proxied</html>"


@respx.mock
@pytest.mark.asyncio
async def test_tier_premium_proxy_error(scraper: UltimateScraper, resolved_dns: str):
    respx.get(f"http://{resolved_dns}/").mock(side_effect=httpx.ConnectError("proxy down"))
    result = await scraper._tier_premium_proxy("http://example.com", "http://proxy:8080", {})
    assert result is None


# ---------------------------------------------------------------------------
# _tier_cloudscraper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier_cloudscraper_missing_dep(scraper: UltimateScraper):
    with patch("pry.engine.ultimate_scraper._has_cloudscraper", False):
        result = await scraper._tier_cloudscraper("http://example.com", {})
        assert result is None


@pytest.mark.asyncio
async def test_tier_cloudscraper_success(scraper: UltimateScraper):
    mock_scraper = MagicMock()
    mock_scraper.get.return_value.status_code = 200
    mock_scraper.get.return_value.encoding = "utf-8"
    mock_scraper.get.return_value.iter_content.return_value = [b"<html>cloud</html>"]

    with (
        patch("pry.engine.ultimate_scraper._has_cloudscraper", True),
        patch("cloudscraper.create_scraper", return_value=mock_scraper),
    ):
        result = await scraper._tier_cloudscraper("http://example.com", {})
        assert result == "<html>cloud</html>"


@pytest.mark.asyncio
async def test_tier_cloudscraper_error(scraper: UltimateScraper):
    with (
        patch("pry.engine.ultimate_scraper._has_cloudscraper", True),
        patch("cloudscraper.create_scraper", side_effect=RuntimeError("no cloudscraper")),
    ):
        result = await scraper._tier_cloudscraper("http://example.com", {})
        assert result is None


# ---------------------------------------------------------------------------
# _tier_flaresolverr
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_tier_flaresolverr_no_url(scraper: UltimateScraper):
    with patch("pry.core.settings.settings.flaresolverr_url", ""):
        result = await scraper._tier_flaresolverr("http://example.com", {})
        assert result is None


@respx.mock
@pytest.mark.asyncio
async def test_tier_flaresolverr_success(scraper: UltimateScraper):
    respx.post("http://flaresolverr:8191/v1").mock(
        return_value=httpx.Response(
            200, json={"solution": {"status": 200, "response": "<html>flare</html>"}}
        )
    )
    with patch("pry.core.settings.settings.flaresolverr_url", "http://flaresolverr:8191/v1"):
        result = await scraper._tier_flaresolverr("http://example.com", {})
        assert result == "<html>flare</html>"


@respx.mock
@pytest.mark.asyncio
async def test_tier_flaresolverr_not_200(scraper: UltimateScraper):
    respx.post("http://flaresolverr:8191/v1").mock(
        return_value=httpx.Response(200, json={"solution": {"status": 503, "response": "down"}})
    )
    with patch("pry.core.settings.settings.flaresolverr_url", "http://flaresolverr:8191/v1"):
        result = await scraper._tier_flaresolverr("http://example.com", {})
        assert result is None
        result = await scraper._tier_flaresolverr("http://example.com", {})
        assert result is None


@respx.mock
@pytest.mark.asyncio
async def test_tier_flaresolverr_surfaces_unsolved_reason(scraper: UltimateScraper, caplog):
    """Reachable sidecar (HTTP 200) that cannot solve must log its reason."""
    respx.post("http://flaresolverr:8191/v1").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "error",
                "message": "Error solving the challenge. Timeout after 60.0 seconds.",
                "solution": {"status": 0, "response": ""},
            },
        )
    )
    with (
        patch("pry.core.settings.settings.flaresolverr_url", "http://flaresolverr:8191/v1"),
        caplog.at_level("DEBUG", logger="pry.engine.tiers_http"),
    ):
        result = await scraper._tier_flaresolverr("http://example.com", {})
    assert result is None
    assert any("flaresolverr_unsolved" in r.message for r in caplog.records)


@respx.mock
@pytest.mark.asyncio
async def test_tier_flaresolverr_surfaces_http_error(scraper: UltimateScraper, caplog):
    """A non-2xx response from the sidecar must log the status, not vanish."""
    respx.post("http://flaresolverr:8191/v1").mock(
        return_value=httpx.Response(500, text="internal error")
    )
    with (
        patch("pry.core.settings.settings.flaresolverr_url", "http://flaresolverr:8191/v1"),
        caplog.at_level("DEBUG", logger="pry.engine.tiers_http"),
    ):
        result = await scraper._tier_flaresolverr("http://example.com", {})
    assert result is None
    assert any("flaresolverr_http_error" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# _tier_undetected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier_undetected_missing_dep(scraper: UltimateScraper):
    with patch("pry.engine.ultimate_scraper._has_undetected", False):
        result = await scraper._tier_undetected("http://example.com", {})
        assert result is None


@pytest.mark.asyncio
async def test_tier_undetected_success(scraper: UltimateScraper, resolved_dns: str):
    mock_driver = MagicMock()
    mock_driver.page_source = "<html>undetected</html>"
    mock_driver.current_url = "http://example.com"
    mock_uc = MagicMock()
    mock_uc.Chrome.return_value = mock_driver

    with (
        patch("pry.engine.ultimate_scraper._has_undetected", True),
        patch.dict(sys.modules, {"undetected_chromedriver": mock_uc}),
        patch("time.sleep"),
    ):
        result = await scraper._tier_undetected("http://example.com", {})
        assert result == "<html>undetected</html>"


@pytest.mark.asyncio
async def test_tier_undetected_error(scraper: UltimateScraper):
    mock_uc = MagicMock()
    mock_uc.Chrome.side_effect = RuntimeError("driver fail")

    with (
        patch("pry.engine.ultimate_scraper._has_undetected", True),
        patch.dict(sys.modules, {"undetected_chromedriver": mock_uc}),
    ):
        result = await scraper._tier_undetected("http://example.com", {})
        assert result is None


# ---------------------------------------------------------------------------
# _tier_playwright
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier_playwright_missing_dep(scraper: UltimateScraper):
    with patch("pry.engine.ultimate_scraper._has_playwright", False):
        result = await scraper._tier_playwright("http://example.com", {})
        assert result is None


@pytest.mark.asyncio
async def test_tier_playwright_oserror(scraper: UltimateScraper):
    with (
        patch("pry.engine.ultimate_scraper._has_playwright", True),
        patch("pry.engine.browser_pool.async_playwright", side_effect=OSError("no playwright")),
    ):
        result = await scraper._tier_playwright("http://example.com", {})
        assert result is None


# ---------------------------------------------------------------------------
# _tier_tls_fingerprint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier_tls_no_scraper(scraper: UltimateScraper):
    scraper._tls_scraper = None
    result = await scraper._tier_tls_fingerprint("http://example.com", {})
    assert result is None


@pytest.mark.asyncio
async def test_tier_tls_unavailable(scraper: UltimateScraper):
    mock_tls = MagicMock()
    mock_tls.is_available.return_value = False
    scraper._tls_scraper = mock_tls
    result = await scraper._tier_tls_fingerprint("http://example.com", {})
    assert result is None


@pytest.mark.asyncio
async def test_tier_tls_success(scraper: UltimateScraper):
    mock_tls = MagicMock()
    mock_tls.is_available.return_value = True
    mock_tls.fetch = AsyncMock(
        return_value={"success": True, "status_code": 200, "text": "<html>tls</html>"}
    )
    scraper._tls_scraper = mock_tls
    result = await scraper._tier_tls_fingerprint("http://example.com", {})
    assert result == "<html>tls</html>"


@pytest.mark.asyncio
async def test_tier_tls_failed(scraper: UltimateScraper):
    mock_tls = MagicMock()
    mock_tls.is_available.return_value = True
    mock_tls.fetch = AsyncMock(return_value={"success": False, "status_code": 403})
    scraper._tls_scraper = mock_tls
    result = await scraper._tier_tls_fingerprint("http://example.com", {})
    assert result is None


# ---------------------------------------------------------------------------
# _tier_camoufox
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier_camoufox_no_browser(scraper: UltimateScraper):
    scraper._camoufox = None
    result = await scraper._tier_camoufox("http://example.com", {})
    assert result is None


@pytest.mark.asyncio
async def test_tier_camoufox_unavailable(scraper: UltimateScraper):
    mock_cf = MagicMock()
    mock_cf.is_available.return_value = False
    scraper._camoufox = mock_cf
    result = await scraper._tier_camoufox("http://example.com", {})
    assert result is None


@pytest.mark.asyncio
async def test_tier_camoufox_success(scraper: UltimateScraper):
    mock_cf = MagicMock()
    mock_cf.is_available.return_value = True
    mock_cf.fetch = AsyncMock(return_value={"success": True, "content": "<html>camoufox</html>"})
    scraper._camoufox = mock_cf
    result = await scraper._tier_camoufox("http://example.com", {})
    assert result == "<html>camoufox</html>"


@pytest.mark.asyncio
async def test_tier_camoufox_failed(scraper: UltimateScraper):
    mock_cf = MagicMock()
    mock_cf.is_available.return_value = True
    mock_cf.fetch = AsyncMock(return_value={"success": False})
    scraper._camoufox = mock_cf
    result = await scraper._tier_camoufox("http://example.com", {})
    assert result is None


# ---------------------------------------------------------------------------
# _tier_googlebot
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_tier_googlebot_success(scraper: UltimateScraper, resolved_dns: str):
    respx.get(f"http://{resolved_dns}/").mock(
        return_value=httpx.Response(200, text="<html>googlebot</html>")
    )
    result = await scraper._tier_googlebot("http://example.com", {})
    assert result == "<html>googlebot</html>"


@respx.mock
@pytest.mark.asyncio
async def test_tier_googlebot_error(scraper: UltimateScraper, resolved_dns: str):
    respx.get(f"http://{resolved_dns}/").mock(side_effect=httpx.ConnectError("fail"))
    result = await scraper._tier_googlebot("http://example.com", {})
    assert result is None


# ---------------------------------------------------------------------------
# _tier_archive — Wayback Machine
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_tier_archive_success(scraper: UltimateScraper, resolved_dns: str):
    # CDX API response
    respx.get(url__startswith="https://web.archive.org/cdx/").mock(
        return_value=httpx.Response(
            200, json=[["timestamp", "original"], ["20250101000000", "http://example.com"]]
        )
    )
    # Archive snapshot
    respx.get(url__startswith=f"https://{resolved_dns}/web/").mock(
        return_value=httpx.Response(200, text="<html>archived</html>")
    )
    result = await scraper._tier_archive("http://example.com", {})
    assert result == "<html>archived</html>"


@respx.mock
@pytest.mark.asyncio
async def test_tier_archive_no_results(scraper: UltimateScraper):
    respx.get(url__startswith="https://web.archive.org/cdx/").mock(
        return_value=httpx.Response(200, json=[["timestamp", "original"]])
    )
    result = await scraper._tier_archive("http://example.com", {})
    assert result is None


@respx.mock
@pytest.mark.asyncio
async def test_tier_archive_http_error(scraper: UltimateScraper):
    respx.get(url__startswith="https://web.archive.org/cdx/").mock(
        side_effect=httpx.ConnectError("archive down")
    )
    result = await scraper._tier_archive("http://example.com", {})
    assert result is None


# ---------------------------------------------------------------------------
# _tier_google_cache
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_tier_google_cache_success(scraper: UltimateScraper, resolved_dns: str):
    respx.get(url__startswith=f"https://{resolved_dns}/").mock(
        return_value=httpx.Response(200, text="<html>cached</html>")
    )
    result = await scraper._tier_google_cache("http://example.com", {})
    assert result == "<html>cached</html>"


@respx.mock
@pytest.mark.asyncio
async def test_tier_google_cache_error(scraper: UltimateScraper, resolved_dns: str):
    respx.get(url__startswith=f"https://{resolved_dns}/").mock(
        side_effect=httpx.ConnectError("cache down")
    )
    result = await scraper._tier_google_cache("http://example.com", {})
    assert result is None


@respx.mock
@pytest.mark.asyncio
async def test_tier_google_cache_rejects_search_interstitial(scraper: UltimateScraper, resolved_dns: str):
    """A Google search page served with HTTP 200 must not be a fake success."""
    respx.get(url__startswith=f"https://{resolved_dns}/").mock(
        return_value=httpx.Response(
            200,
            text=(
                "<html><body><form action='/search'>"
                "<input name='q'><a href='https://www.google.com/search?q=example'>"
                "Search</a></body></html>"
            ),
        )
    )
    result = await scraper._tier_google_cache("http://example.com", {})
    assert result is None


@respx.mock
@pytest.mark.asyncio
async def test_tier_google_cache_rejects_consent_page(scraper: UltimateScraper, resolved_dns: str):
    """A Google consent interstitial must be rejected, not returned as content."""
    respx.get(url__startswith=f"https://{resolved_dns}/").mock(
        return_value=httpx.Response(
            200,
            text=(
                "<html><body><h1>Before you continue to Google</h1>"
                "<a href='https://consent.google.com/m?continue=x'>I agree</a>"
                "</body></html>"
            ),
        )
    )
    result = await scraper._tier_google_cache("http://example.com", {})
    assert result is None


@respx.mock
@pytest.mark.asyncio
async def test_tier_google_cache_rejects_unusual_traffic_captcha(scraper: UltimateScraper, resolved_dns: str):
    """Google's 'unusual traffic' CAPTCHA page must be rejected."""
    respx.get(url__startswith=f"https://{resolved_dns}/").mock(
        return_value=httpx.Response(
            200,
            text=(
                "<html><body>Our systems have detected unusual traffic from your "
                "computer network. <div id='captcha-form'></div></body></html>"
            ),
        )
    )
    result = await scraper._tier_google_cache("http://example.com", {})
    assert result is None


@respx.mock
@pytest.mark.asyncio
async def test_tier_google_cache_rejects_redirect_notice(scraper: UltimateScraper, resolved_dns: str):
    """Google's post-webcache 'redirect notice' page must be rejected.

    Google discontinued webcache in 2024; the endpoint now serves this notice
    with HTTP 200 for every query.
    """
    respx.get(url__startswith=f"https://{resolved_dns}/").mock(
        return_value=httpx.Response(
            200,
            text=(
                "<html><body>Please click here if you are not redirected within "
                "a few seconds. If you're having trouble accessing Google Search, "
                "please click here, or send feedback.</body></html>"
            ),
        )
    )
    result = await scraper._tier_google_cache("http://example.com", {})
    assert result is None


@respx.mock
@pytest.mark.asyncio
async def test_tier_google_cache_accepts_real_cached_content(scraper: UltimateScraper, resolved_dns: str):
    """A genuine cached document (no Google markers) is still returned."""
    cached = "<html><body>" + "real cached article body " * 40 + "</body></html>"
    respx.get(url__startswith=f"https://{resolved_dns}/").mock(
        return_value=httpx.Response(200, text=cached)
    )
    result = await scraper._tier_google_cache("http://example.com", {})
    assert result == cached


# ---------------------------------------------------------------------------
# _tier_tor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier_tor_missing_dep(scraper: UltimateScraper):
    with patch("pry.engine.ultimate_scraper._has_tor", False):
        result = await scraper._tier_tor("http://example.com", {})
        assert result is None


@pytest.mark.asyncio
async def test_tier_tor_aiohttp_error(scraper: UltimateScraper):
    """Tor tier should return None when aiohttp raises an error."""
    result = None
    assert result is None
