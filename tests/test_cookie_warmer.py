# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for the cookie warmer: domain→page scheduling, persistence, expiry.

Playwright is installed but a real browser launch is not available/desired in
unit tests. ``warm_for_site`` imports ``async_playwright`` lazily inside the
method, so we patch ``playwright.async_api.async_playwright`` with a mock
browser/context/page chain. ``WARMER_DIR`` is redirected to a tmp dir so no
files are written into the repo's ``warmed_cookies/`` directory.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cookie_warmer
from cookie_warmer import WARMING_PAGES, CookieWarmer

# ── Domain → warming page scheduling ────────────────────────────


def test_warming_pages_catalog_has_generic_fallback() -> None:
    assert "generic" in WARMING_PAGES
    assert len(WARMING_PAGES["generic"]) >= 3


@pytest.mark.parametrize(
    ("domain", "expected_key"),
    [
        ("amazon.com", "amazon"),
        ("www.ebay.com", "ebay"),
        ("shopify.com", "shopify"),
        ("twitter.com", "twitter"),
        ("www.linkedin.com", "linkedin"),
        ("unknown-site.example", "generic"),
        ("AMAZON.CO.UK", "amazon"),  # case-insensitive
    ],
)
def test_domain_key_resolution(domain: str, expected_key: str) -> None:
    key = next((k for k in WARMING_PAGES if k in domain.lower()), "generic")
    assert key == expected_key


def test_pages_are_limited_to_requested_count() -> None:
    key = next((k for k in WARMING_PAGES if k in "amazon.com"), "generic")
    pages = WARMING_PAGES[key][:3]
    assert len(pages) <= 3
    assert pages == WARMING_PAGES[key][:3]


# ── warm_for_site ───────────────────────────────────────────────


def _mock_playwright(cookies: list[dict[str, str]] | None = None) -> MagicMock:
    """Build a mocked playwright async chain returning canned cookies."""
    pw = MagicMock()
    pw.chromium.launch = AsyncMock(return_value=pw)
    pw.new_context = AsyncMock(return_value=pw)
    pw.add_init_script = AsyncMock()
    pw.new_page = AsyncMock(return_value=pw)
    pw.goto = AsyncMock()
    pw.evaluate = AsyncMock()
    pw.wait_for_timeout = AsyncMock()
    pw.cookies = AsyncMock(
        return_value=cookies
        or [
            {
                "name": "session",
                "value": "abc123",
                "domain": ".amazon.com",
                "path": "/",
                "expires": 1893456000,
                "httpOnly": True,
                "secure": True,
            }
        ]
    )
    pw.close = AsyncMock()

    mock_async_pw = AsyncMock()
    mock_async_pw.__aenter__.return_value = pw
    mock_async_pw.__aexit__.return_value = False
    return mock_async_pw


async def test_warm_for_site_writes_persisted_cookie_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cookie_warmer, "WARMER_DIR", tmp_path)
    warmer = CookieWarmer()
    mock_pw = _mock_playwright()

    with patch("playwright.async_api.async_playwright", return_value=mock_pw):
        result = await warmer.warm_for_site(
            "amazon.com", session_id="sess-1", pages_to_visit=2, min_delay=0.0, max_delay=0.0
        )

    assert result["success"] is True
    assert result["session_id"] == "sess-1"
    assert result["domain"] == "amazon.com"
    assert result["cookie_count"] == 1
    assert "amazon.com" in result["pages_visited"][0]

    cookie_file = tmp_path / "sess-1.json"
    assert cookie_file.exists()
    data = json.loads(cookie_file.read_text())
    assert data["domain"] == "amazon.com"
    assert data["session_id"] == "sess-1"
    assert data["cookies"][0]["name"] == "session"
    assert data["cookies"][0]["httpOnly"] is True
    assert "warmed_at" in data
    assert "expires_at" in data


async def test_warm_for_site_generates_session_id_when_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cookie_warmer, "WARMER_DIR", tmp_path)
    warmer = CookieWarmer()
    mock_pw = _mock_playwright()

    with patch("playwright.async_api.async_playwright", return_value=mock_pw):
        result = await warmer.warm_for_site(
            "ebay.com", pages_to_visit=1, min_delay=0.0, max_delay=0.0
        )

    assert result["success"] is True
    assert result["session_id"].startswith("ebay.com_")


async def test_warm_for_site_selects_generic_pages_for_unknown_domain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cookie_warmer, "WARMER_DIR", tmp_path)
    warmer = CookieWarmer()
    mock_pw = _mock_playwright()

    with patch("playwright.async_api.async_playwright", return_value=mock_pw) as mock_cls:
        await warmer.warm_for_site(
            "mystery-domain.xyz",
            session_id="sess-g",
            pages_to_visit=1,
            min_delay=0.0,
            max_delay=0.0,
        )

    page_gotos = mock_cls.return_value.__aenter__.return_value.goto
    assert page_gotos.await_count == 1
    first_url = page_gotos.await_args.args[0]
    assert first_url in WARMING_PAGES["generic"]


async def test_warm_for_site_pages_visited_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cookie_warmer, "WARMER_DIR", tmp_path)
    warmer = CookieWarmer()
    mock_pw = _mock_playwright()

    with patch("playwright.async_api.async_playwright", return_value=mock_pw) as mock_cls:
        result = await warmer.warm_for_site(
            "shopify.com", session_id="sess-s", pages_to_visit=5, min_delay=0.0, max_delay=0.0
        )

    gotos = mock_cls.return_value.__aenter__.return_value.goto
    # shopify only has 2 pages in the catalog → capped at 2
    assert gotos.await_count == 2
    assert len(result["pages_visited"]) == 2


async def test_warm_for_site_handles_page_goto_failure(tmp_path, monkeypatch) -> None:
    """A failing page visit must not abort the whole warm-up."""
    monkeypatch.setattr(cookie_warmer, "WARMER_DIR", tmp_path)
    warmer = CookieWarmer()
    mock_pw = _mock_playwright()
    mock_pw.__aenter__.return_value.goto.side_effect = RuntimeError("blocked")

    with patch("playwright.async_api.async_playwright", return_value=mock_pw):
        result = await warmer.warm_for_site(
            "amazon.com", session_id="sess-fail", pages_to_visit=2, min_delay=0.0, max_delay=0.0
        )

    assert result["success"] is True  # continues despite page failures
    assert result["cookie_count"] == 1  # canned cookies still collected


# ── Persistence: get_warmed_cookies ─────────────────────────────


def test_get_warmed_cookies_missing_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cookie_warmer, "WARMER_DIR", tmp_path)
    assert CookieWarmer().get_warmed_cookies("does-not-exist") is None


def test_get_warmed_cookies_returns_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cookie_warmer, "WARMER_DIR", tmp_path)
    data = {
        "domain": "amazon.com",
        "session_id": "sess-x",
        "warmed_at": datetime.now(UTC).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
        "pages_visited": ["https://www.amazon.com/"],
        "cookies": [{"name": "a", "value": "b"}],
        "user_agent": "Mozilla/5.0",
    }
    (tmp_path / "sess-x.json").write_text(json.dumps(data))

    loaded = CookieWarmer().get_warmed_cookies("sess-x")
    assert loaded is not None
    assert loaded["session_id"] == "sess-x"
    assert loaded["domain"] == "amazon.com"


def test_get_warmed_cookies_expired_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cookie_warmer, "WARMER_DIR", tmp_path)
    data = {
        "domain": "amazon.com",
        "session_id": "sess-old",
        "warmed_at": (datetime.now(UTC) - timedelta(days=40)).isoformat(),
        "expires_at": (datetime.now(UTC) - timedelta(days=10)).isoformat(),
        "pages_visited": [],
        "cookies": [],
        "user_agent": "Mozilla/5.0",
    }
    (tmp_path / "sess-old.json").write_text(json.dumps(data))

    assert CookieWarmer().get_warmed_cookies("sess-old") is None


def test_get_warmed_cookies_corrupt_json_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cookie_warmer, "WARMER_DIR", tmp_path)
    (tmp_path / "sess-bad.json").write_text("{not valid json")

    assert CookieWarmer().get_warmed_cookies("sess-bad") is None


# ── list_sessions ───────────────────────────────────────────────


def test_list_sessions_returns_all_valid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cookie_warmer, "WARMER_DIR", tmp_path)
    for sid in ("s1", "s2"):
        (tmp_path / f"{sid}.json").write_text(
            json.dumps(
                {
                    "domain": "x.com",
                    "session_id": sid,
                    "warmed_at": datetime.now(UTC).isoformat(),
                    "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
                    "cookies": [{"name": "c"}],
                }
            )
        )
    # Corrupt file must be skipped, not raise.
    (tmp_path / "broken.json").write_text("garbage")

    sessions = CookieWarmer().list_sessions()
    assert {s["session_id"] for s in sessions} == {"s1", "s2"}
    assert all(s["cookie_count"] == 1 for s in sessions)


def test_list_sessions_empty_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cookie_warmer, "WARMER_DIR", tmp_path)
    assert CookieWarmer().list_sessions() == []
