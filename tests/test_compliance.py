# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for legal compliance engine."""

from compliance import (
    classify_tos,
    detect_jurisdiction,
    tag_sensitive_data,
)


def test_classify_tos_restrictive() -> None:
    text = "No scraping, no crawling, no automated access. All rights reserved."
    result = classify_tos(text)
    assert result["classification"] == "restrictive"


def test_classify_tos_permissive() -> None:
    text = "This data is freely available under Creative Commons Attribution 4.0."
    result = classify_tos(text)
    assert result["classification"] == "permissive"


def test_classify_tos_moderate() -> None:
    text = "Personal use only. Attribution required. Fair use applies."
    result = classify_tos(text)
    assert result["classification"] == "moderate"


def test_classify_tos_empty() -> None:
    result = classify_tos("")
    assert result["confidence"] in ("low", "medium")


def test_detect_jurisdiction_eu() -> None:
    result = detect_jurisdiction("https://example.de")
    assert result["jurisdiction"] == "eu"


def test_detect_jurisdiction_us() -> None:
    result = detect_jurisdiction("https://example.com")
    assert result["jurisdiction"] == "us"


def test_detect_jurisdiction_ca() -> None:
    result = detect_jurisdiction("https://example.ca")
    assert result["jurisdiction"] == "ca"


def test_detect_jurisdiction_gdpr_signal() -> None:
    html = "We comply with the General Data Protection Regulation (GDPR)."
    result = detect_jurisdiction("https://example.com", html)
    assert result["gdpr_signals"] is True


def test_detect_jurisdiction_ccpa_signal() -> None:
    html = "CCPA California Consumer Privacy Act rights."
    result = detect_jurisdiction("https://example.com", html)
    assert result["ccpa_signals"] is True


def test_tag_sensitive_data_pii() -> None:
    html = "Contact John Smith at john@example.com or call 555-0100."
    result = tag_sensitive_data(html)
    assert result["has_pii"] is True
    assert result["has_contact"] is True


def test_tag_sensitive_data_financial() -> None:
    html = "Total cost: $1,299.00. Invoice #1234."
    result = tag_sensitive_data(html)
    assert result["has_financial"] is True


def test_tag_sensitive_data_health() -> None:
    html = "Patient diagnosis and treatment records are confidential."
    result = tag_sensitive_data(html)
    assert result["has_health"] is True


def test_tag_sensitive_data_empty() -> None:
    result = tag_sensitive_data("<html><body><p>Hello</p></body></html>")
    assert result["has_pii"] is False
    assert result["has_financial"] is False
