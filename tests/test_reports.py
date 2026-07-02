# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for white-label report generation."""

from reports import generate_report, list_reports


def test_generate_competitive_report() -> None:
    result = generate_report(
        "competitive_analysis",
        {
            "competitors": [
                {
                    "name": "Competitor A",
                    "price": 99.99,
                    "price_change": 5.0,
                    "last_updated": "2024-01-01",
                },
                {
                    "name": "Competitor B",
                    "price": 149.99,
                    "price_change": -2.5,
                    "last_updated": "2024-01-02",
                },
            ],
            "changes": ["Competitor A lowered prices on 3 products"],
        },
    )
    assert result["success"] is True
    assert result["type"] == "competitive_analysis"
    assert result["format"] == "html"


def test_generate_price_report() -> None:
    result = generate_report(
        "price_monitor",
        {
            "products": [
                {
                    "name": "Product X",
                    "previous_price": 100,
                    "current_price": 95,
                    "price_change": -5.0,
                },
                {
                    "name": "Product Y",
                    "previous_price": 50,
                    "current_price": 55,
                    "price_change": 10.0,
                },
            ],
        },
    )
    assert result["success"] is True


def test_generate_seo_report() -> None:
    result = generate_report(
        "seo_audit",
        {
            "seo_data": {"title": "My Page", "word_count": 1200, "has_schema": True},
            "changes": [{"field": "title", "severity": "high", "to": "New Title"}],
        },
    )
    assert result["success"] is True


def test_generate_content_report() -> None:
    result = generate_report(
        "content_tracker",
        {
            "pages": [
                {
                    "title": "Homepage",
                    "url": "https://example.com",
                    "status": "unchanged",
                    "word_count": 500,
                }
            ],
            "changes": [],
        },
    )
    assert result["success"] is True


def test_generate_with_branding() -> None:
    result = generate_report(
        "competitive_analysis",
        {"competitors": []},
        branding={"agency_name": "Acme Analytics", "brand_color": "#ff0000"},
    )
    assert result["success"] is True


def test_generate_unknown_type() -> None:
    result = generate_report("unknown_type", {})
    assert "error" in result


def test_list_reports() -> None:
    generate_report("competitive_analysis", {"competitors": []})
    reports = list_reports()
    assert len(reports) >= 1
