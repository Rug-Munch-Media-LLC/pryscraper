# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for data enrichment pipeline."""

from pry.api.enrichment import (
    TECH_PATTERNS,
    detect_tech_stack,
    extract_company_info,
    extract_social_profiles,
)


def test_detect_tech_wordpress() -> None:
    html = '<html><head><link rel="stylesheet" href="/wp-content/themes/style.css"></head></html>'
    result = detect_tech_stack(html)
    assert "wordpress" in result["detected"]


def test_detect_tech_shopify() -> None:
    html = '<html><body><script src="https://cdn.shopify.com/s/files/1/0000/0000/files/script.js"></script></body></html>'
    result = detect_tech_stack(html)
    assert "shopify" in result["detected"]


def test_detect_tech_nextjs() -> None:
    html = "<html><head><script>window.__NEXT_DATA__ = {}</script></head></html>"
    result = detect_tech_stack(html)
    assert "nextjs" in result["detected"]


def test_detect_tech_cloudflare() -> None:
    html = "<html></html>"
    result = detect_tech_stack(html, {"server": "cloudflare"})
    assert "cloudflare" in result["detected"]


def test_detect_tech_empty() -> None:
    result = detect_tech_stack("", {})
    assert result["count"] == 0


def test_extract_social_twitter() -> None:
    html = 'Follow us on <a href="https://twitter.com/pry_scraper">Twitter</a>'
    result = extract_social_profiles(html)
    assert "pry_scraper" in str(result["profiles"])


def test_extract_social_linkedin() -> None:
    html = 'Connect on <a href="https://linkedin.com/company/pry-inc">LinkedIn</a>'
    result = extract_social_profiles(html)
    assert "pry-inc" in str(result["profiles"])


def test_extract_company_email() -> None:
    html = "Contact us at info@example.com for inquiries"
    result = extract_company_info(html)
    assert len(result.get("emails", [])) >= 1
    assert "info@example.com" in result["emails"]


def test_extract_company_founded() -> None:
    html = "Founded in 2020, we have been growing ever since."
    result = extract_company_info(html)
    assert result.get("founded_year") == "2020"


def test_tech_patterns_exist() -> None:
    assert "wordpress" in TECH_PATTERNS
    assert "shopify" in TECH_PATTERNS
    assert "nextjs" in TECH_PATTERNS
    assert "cloudflare" in TECH_PATTERNS
    assert "stripe" in TECH_PATTERNS
