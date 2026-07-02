# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for block detector."""

from scraper import BlockDetector


def test_block_detector_cloudflare() -> None:
    detector = BlockDetector()
    html = """<html><head><title>Attention Required! | Cloudflare</title>
    <body>Please complete the security check to access this site.
    This is performed by Cloudflare.</body></html>"""
    result = detector.detect(html, 403, {"server": "cloudflare"})
    assert result["blocked"] is True
    assert result["vendor"] == "cloudflare"
    assert result["tier"] == "vendor"


def test_block_detector_ok() -> None:
    detector = BlockDetector()
    html = "<html><body><h1>Welcome</h1><p>" + "x" * 10000 + "</p></body></html>"
    result = detector.detect(html, 200, {})
    assert result["blocked"] is False


def test_block_detector_403() -> None:
    detector = BlockDetector()
    result = detector.detect("<html></html>", 403, {})
    assert result["blocked"] is True
    assert result["tier"] == "generic"


def test_block_detector_429() -> None:
    detector = BlockDetector()
    result = detector.detect("<html></html>", 429, {})
    assert result["blocked"] is True
    assert result["vendor"] == "rate_limit"


def test_block_detector_empty_page() -> None:
    detector = BlockDetector(min_content_length=100)
    html = "<html><body><p>Short</p></body></html>"
    result = detector.detect(html, 200, {})
    assert result["blocked"] is True
    assert result["tier"] == "structural"


def test_block_detector_akamai() -> None:
    detector = BlockDetector()
    html = """<html><head><title>Access Denied</title>
    <body>This request was blocked by Akamai.
    Reference #0.a1b2c3d4e5f6g7h8.</body></html>"""
    result = detector.detect(html, 403, {"server": "AkamaiGHost"})
    assert result["blocked"] is True
    assert result["vendor"] == "akamai"
    assert result["tier"] == "vendor"


def test_block_detector_datadome() -> None:
    detector = BlockDetector()
    html = """<html><head><title>Blocked</title>
    <body>We believe you are a bot. Captcha required by DataDome.</body></html>"""
    result = detector.detect(html, 403, {})
    assert result["blocked"] is True
    assert result["vendor"] == "datadome"
    assert result["tier"] == "vendor"


def test_block_detector_imperva() -> None:
    detector = BlockDetector()
    html = """<html><head><title>Blocked</title>
    <body>Request blocked by Imperva. Malicious activity detected.</body></html>"""
    result = detector.detect(html, 403, {})
    assert result["blocked"] is True
    assert result["vendor"] == "imperva"
    assert result["tier"] == "vendor"


def test_block_detector_generic_pattern() -> None:
    detector = BlockDetector()
    html = """<html><head><title>Rate Limited</title>
    <body>Too many requests. Please try again later.</body></html>"""
    result = detector.detect(html, 200, {})
    assert result["blocked"] is True
    assert result["tier"] == "generic"


def test_block_detector_no_content_empty() -> None:
    detector = BlockDetector()
    result = detector.detect("", 200, {})
    assert result["blocked"] is False
