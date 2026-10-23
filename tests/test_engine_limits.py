"""Engine hardening tests: response caps, browser timeouts, JSON contracts,
and user-selector validation.

No network, no real browser — every external edge is faked.
"""

from __future__ import annotations

import pytest

from pry.core.errors import InvalidRequestError
from pry.engine import schema_extract as se, tiers_browser, url_guard
from pry.engine.adaptive_selector import AdaptiveSelector
from pry.engine.ultimate_scraper import normalize_json_payload

_HOSTILE = "#" + "a" * 10_000  # exceeds extraction.css._MAX_SELECTOR_LENGTH


class _FakeResponse:
    """Minimal streamed httpx.Response stand-in for safe_get."""

    def __init__(self, body: bytes) -> None:
        self._body = body
        self.headers: dict[str, str] = {}
        self.extensions: dict[str, object] = {}
        self.status_code = 200
        self.closed = False

    @property
    def is_redirect(self) -> bool:
        return False

    async def aiter_bytes(self):
        for i in range(0, len(self._body), 65536):
            yield self._body[i : i + 65536]

    async def aclose(self) -> None:
        self.closed = True


class _FakeClient:
    follow_redirects = False


class TestResponseCap:
    async def test_oversize_body_is_truncated_and_flagged(self, monkeypatch):
        body = b"x" * (url_guard.MAX_RESPONSE_BYTES + 4096)
        response = _FakeResponse(body)
        monkeypatch.setattr(url_guard, "validate_redirect_url", lambda url: url)
        monkeypatch.setattr("pry.engine.url_pinning.pinned_get", _fake_pinned(response))

        result = await url_guard.safe_get(_FakeClient(), "https://example.com/")

        assert len(result._content) == url_guard.MAX_RESPONSE_BYTES
        assert result._content == body[: url_guard.MAX_RESPONSE_BYTES]
        assert result.extensions["pry_truncated"] is True
        assert result.closed is True

    async def test_small_body_is_not_flagged(self, monkeypatch):
        response = _FakeResponse(b"hello")
        monkeypatch.setattr(url_guard, "validate_redirect_url", lambda url: url)
        monkeypatch.setattr("pry.engine.url_pinning.pinned_get", _fake_pinned(response))

        result = await url_guard.safe_get(_FakeClient(), "https://example.com/")

        assert result._content == b"hello"
        assert result.extensions["pry_truncated"] is False


def _fake_pinned(response):
    async def _pinned(client, url, kwargs, **_kwargs):
        assert kwargs.get("stream") is True
        return response

    return _pinned


class _FakeContext:
    async def add_init_script(self, script: str) -> None:
        return None

    async def new_page(self):
        raise TimeoutError("page load timed out")

    async def close(self) -> None:
        return None


class _FakeBrowser:
    async def new_context(self, **kwargs):
        return _FakeContext()


class _FakePool:
    async def get_playwright_browser(self):
        return _FakeBrowser()


class _FakeScraper(tiers_browser.TierBrowserMixin):
    def _rotate_ua(self) -> str:
        return "test-agent"


class TestPlaywrightTimeout:
    async def test_timeout_becomes_tier_failure(self, monkeypatch):
        monkeypatch.setattr(tiers_browser, "get_browser_pool", lambda: _FakePool())
        monkeypatch.setattr(
            tiers_browser, "_us_flag", lambda name: None if name == "_stealth_engine" else True
        )
        monkeypatch.setattr(tiers_browser, "install_route_guard", lambda page: None)

        assert await _FakeScraper()._tier_playwright("https://example.com/", {}) is None


class TestGraphQLContract:
    def test_data_envelope_is_normalised(self):
        result = normalize_json_payload(
            {"status": "ok", "raw_html": '{"data": {"user": {"id": 1}}}', "content": ""}
        )

        assert result["is_json"] is True
        assert result["json_data"] == {"data": {"user": {"id": 1}}}
        assert "<pre>" in result["raw_html"]
        assert '"user"' in result["content"]

    def test_html_body_is_untouched(self):
        payload = {"status": "ok", "raw_html": "<html><body>hi</body></html>"}
        assert normalize_json_payload(dict(payload)) == payload


class TestSelectorValidation:
    def test_adaptive_selector_rejects_hostile_selector(self):
        with pytest.raises(InvalidRequestError):
            AdaptiveSelector("<html><body><p>x</p></body></html>").select("x", _HOSTILE)

    async def test_extract_table_rejects_hostile_selector(self):
        with pytest.raises(InvalidRequestError):
            await se.extract_table("https://example.com/", _HOSTILE)
