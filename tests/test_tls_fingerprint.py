# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for TLS fingerprint impersonation config parsing and fetch behavior.

curl_cffi is an optional dependency and is NOT installed in the test venv.
These tests therefore monkeypatch ``tls_fingerprint._has_curl_cffi`` and the
``AsyncSession`` symbol so the success paths can be exercised without a real
network call or a live curl_cffi install.
"""

from unittest.mock import AsyncMock, patch

import pytest

import tls_fingerprint
from tls_fingerprint import BROWSER_FINGERPRINTS, TLSScraper

# ── Fingerprint catalog / config parsing ────────────────────────


def test_fingerprint_catalog_has_modern_chrome() -> None:
    assert "chrome131" in BROWSER_FINGERPRINTS
    assert "chrome124" in BROWSER_FINGERPRINTS


def test_fingerprint_catalog_covers_major_browsers() -> None:
    assert "firefox132" in BROWSER_FINGERPRINTS
    assert "safari17_0" in BROWSER_FINGERPRINTS
    assert "edge127" in BROWSER_FINGERPRINTS


def test_default_impersonate_valid_kept() -> None:
    s = TLSScraper(default_impersonate="firefox132")
    assert s.default_impersonate == "firefox132"


def test_default_impersonate_invalid_falls_back_to_chrome() -> None:
    s = TLSScraper(default_impersonate="netscape42")
    assert s.default_impersonate == "chrome"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("chrome131", "chrome131"),
        ("", "chrome"),
        ("safari17_0", "safari17_0"),
        ("NOT_A_BROWSER", "chrome"),
    ],
)
def test_default_impersonate_validation(raw: str, expected: str) -> None:
    s = TLSScraper(default_impersonate=raw)
    assert s.default_impersonate == expected


def test_is_available_reflects_curl_cffi_installed() -> None:
    with patch.object(tls_fingerprint, "_has_curl_cffi", True):
        assert TLSScraper().is_available() is True
    with patch.object(tls_fingerprint, "_has_curl_cffi", False):
        assert TLSScraper().is_available() is False


# ── fetch() behavior ────────────────────────────────────────────


async def test_fetch_returns_error_when_curl_cffi_missing() -> None:
    with patch.object(tls_fingerprint, "_has_curl_cffi", False):
        result = await TLSScraper().fetch("https://example.com")
    assert result["success"] is False
    assert "curl_cffi" in result["error"]


async def test_fetch_passes_impersonate_to_session() -> None:
    session = AsyncMock()
    session.get.return_value.status_code = 200
    session.get.return_value.text = "<html>ok</html>"
    session.get.return_value.content = b"<html>ok</html>"
    session.get.return_value.headers = {"content-type": "text/html"}
    session.get.return_value.cookies = {"a": "b"}
    session.get.return_value.url = "https://example.com/"
    session.__aenter__.return_value = session
    session.__aexit__.return_value = False

    with (
        patch.object(tls_fingerprint, "_has_curl_cffi", True),
        patch("tls_fingerprint.AsyncSession", create=True, return_value=session) as mock_cls,
    ):
        result = await TLSScraper(default_impersonate="firefox132").fetch(
            "https://example.com", impersonate="chrome124"
        )

    assert result["success"] is True
    assert result["status_code"] == 200
    assert result["impersonate"] == "chrome124"
    call_kwargs = mock_cls.call_args.kwargs
    assert call_kwargs["impersonate"] == "chrome124"
    assert call_kwargs["timeout"] == 30
    assert call_kwargs["allow_redirects"] is True


async def test_fetch_invalid_impersonate_falls_back_to_chrome() -> None:
    session = AsyncMock()
    session.get.return_value.status_code = 200
    session.get.return_value.text = "x"
    session.get.return_value.content = b"x"
    session.get.return_value.headers = {}
    session.get.return_value.cookies = {}
    session.get.return_value.url = "https://example.com/"
    session.__aenter__.return_value = session
    session.__aexit__.return_value = False

    with (
        patch.object(tls_fingerprint, "_has_curl_cffi", True),
        patch("tls_fingerprint.AsyncSession", create=True, return_value=session) as mock_cls,
    ):
        result = await TLSScraper().fetch("https://example.com", impersonate="bad-ua")

    assert result["impersonate"] == "chrome"
    assert mock_cls.call_args.kwargs["impersonate"] == "chrome"


async def test_fetch_merges_custom_headers() -> None:
    session = AsyncMock()
    session.get.return_value.status_code = 200
    session.get.return_value.text = "x"
    session.get.return_value.content = b"x"
    session.get.return_value.headers = {}
    session.get.return_value.cookies = {}
    session.get.return_value.url = "https://example.com/"
    session.__aenter__.return_value = session
    session.__aexit__.return_value = False

    with (
        patch.object(tls_fingerprint, "_has_curl_cffi", True),
        patch("tls_fingerprint.AsyncSession", create=True, return_value=session) as mock_cls,
    ):
        await TLSScraper().fetch("https://example.com", headers={"X-Custom": "yes"})

    sent_headers = mock_cls.call_args.kwargs["headers"]
    assert sent_headers["X-Custom"] == "yes"
    assert sent_headers["Accept-Language"] == "en-US,en;q=0.9"  # default retained


async def test_fetch_exception_returns_error_dict() -> None:
    session = AsyncMock()
    session.get.side_effect = RuntimeError("boom")
    session.__aenter__.return_value = session
    session.__aexit__.return_value = False

    with (
        patch.object(tls_fingerprint, "_has_curl_cffi", True),
        patch("tls_fingerprint.AsyncSession", create=True, return_value=session),
    ):
        result = await TLSScraper().fetch("https://example.com")

    assert result["success"] is False
    assert "boom" in result["error"]


# ── fetch_with_rotation() ───────────────────────────────────────


async def test_fetch_with_rotation_returns_first_success() -> None:
    s = TLSScraper()
    # First two fingerprints fail (5xx), third succeeds.
    results = [
        {"success": True, "status_code": 503},
        {"success": True, "status_code": 500},
        {"success": True, "status_code": 200},
    ]
    with patch.object(s, "fetch", new=AsyncMock(side_effect=results)) as mock_fetch:
        out = await s.fetch_with_rotation("https://example.com", fingerprints=["fp1", "fp2", "fp3"])

    assert out["success"] is True
    assert out["matched_fingerprint"] == "fp3"
    assert mock_fetch.await_count == 3


async def test_fetch_with_rotation_stops_after_first_2xx() -> None:
    s = TLSScraper()
    results = [
        {"success": True, "status_code": 200},
        {"success": True, "status_code": 200},
    ]
    with patch.object(s, "fetch", new=AsyncMock(side_effect=results)) as mock_fetch:
        await s.fetch_with_rotation("https://example.com", fingerprints=["a", "b", "c"])

    assert mock_fetch.await_count == 1  # short-circuits on success


async def test_fetch_with_rotation_all_fail() -> None:
    s = TLSScraper()
    results = [
        {"success": True, "status_code": 503},
        {"success": True, "status_code": 429},
        {"success": False, "error": "nope"},
    ]
    with patch.object(s, "fetch", new=AsyncMock(side_effect=results)):
        out = await s.fetch_with_rotation("https://example.com", fingerprints=["a", "b", "c"])

    assert out["success"] is False
    assert out["attempts"] == 3
    assert "All fingerprints failed" in out["error"]


async def test_fetch_with_rotation_defaults_to_first_ten_fingerprints() -> None:
    s = TLSScraper()
    with patch.object(
        s, "fetch", new=AsyncMock(return_value={"success": True, "status_code": 200})
    ) as mock_fetch:
        out = await s.fetch_with_rotation("https://example.com")

    assert out["success"] is True
    assert out["matched_fingerprint"] == BROWSER_FINGERPRINTS[0]
    assert mock_fetch.await_count == 1
