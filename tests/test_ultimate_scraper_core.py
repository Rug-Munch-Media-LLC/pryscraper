"""UltimateScraper construction, URL validation, UA/header and result helpers."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

import pytest

from pry.engine.ultimate_scraper import UltimateScraper
from tests.ultimate_scraper_support import (  # noqa: F401 — fixtures for this module
    VALID_HTML,
    scraper,
)


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


@pytest.mark.asyncio
async def test_scrape_invalid_url_returns_error(scraper: UltimateScraper):
    result = await scraper.scrape("not-a-url")
    assert result["status"] == "error"


def test_rotate_ua_returns_string(scraper: UltimateScraper):
    ua = scraper._rotate_ua()
    assert isinstance(ua, str)
    assert len(ua) > 20


def test_rotate_ua_changes(scraper: UltimateScraper):
    uas = {scraper._rotate_ua() for _ in range(5)}
    assert len(uas) > 1


def test_build_headers_contains_required(scraper: UltimateScraper):
    h = scraper._build_headers("http://example.com")
    for k in ["User-Agent", "Accept", "Accept-Language"]:
        assert k in h


def test_is_valid_none(scraper: UltimateScraper):
    assert scraper._is_valid(None) is False


def test_is_valid_empty(scraper: UltimateScraper):
    assert scraper._is_valid("") is False


def test_is_valid_short(scraper: UltimateScraper):
    assert scraper._is_valid("ab" * 100) is False


def test_is_valid_ok(scraper: UltimateScraper):
    assert scraper._is_valid(VALID_HTML) is True


def test_is_valid_body_text_too_short(scraper: UltimateScraper):
    body = "<body>" + "x" * 40 + "</body>"
    assert scraper._is_valid(body) is False


def test_result_success_format(scraper: UltimateScraper):
    result = scraper._result("http://example.com", VALID_HTML, "direct")
    assert result["status"] == "ok"
    assert result["url"] == "http://example.com"
    assert result["method"] == "direct"
    assert "raw_html" in result


def test_result_contains_block_signal(scraper: UltimateScraper):
    result = scraper._result(
        "http://example.com",
        VALID_HTML,
        "direct",
        block_signal={"kind": "captcha", "confidence": 0.8},
    )
    assert result["block_signal"]["kind"] == "captcha"
