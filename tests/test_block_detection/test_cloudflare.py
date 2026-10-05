# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Cloudflare signal detection."""

from __future__ import annotations

from pry.engine.block_detection import detect_block

from .conftest import CF_403_HTML, CF_CHALLENGE_HTML


def test_cloudflare_challenge_body_markers() -> None:
    signal = detect_block(CF_CHALLENGE_HTML, 403, {"server": "cloudflare"})
    assert signal.kind == "cloudflare"
    assert signal.confidence == 0.90
    assert signal.recommended_escalation == "stealth"
    assert any("just a moment" in e for e in signal.evidence)
    assert any("cf-chl-" in e for e in signal.evidence)


def test_cloudflare_cf_mitigated_header() -> None:
    signal = detect_block("<html><body>blocked</body></html>", 403, {"cf-mitigated": "challenge"})
    assert signal.kind == "cloudflare"
    assert signal.confidence == 0.97
    assert signal.recommended_escalation == "stealth"
    assert "header cf-mitigated" in signal.evidence


def test_cloudflare_403_with_cf_ray_header() -> None:
    signal = detect_block(CF_403_HTML, 403, {"cf-ray": "abc123-fra", "server": "cloudflare"})
    assert signal.kind == "cloudflare"
    assert signal.confidence == 0.95
    assert signal.recommended_escalation == "stealth"
    assert any("cf-ray" in e for e in signal.evidence)


def test_cloudflare_header_keys_case_insensitive() -> None:
    signal = detect_block("<html></html>", 403, {"CF-Ray": "abc123-fra"})
    assert signal.kind == "cloudflare"
    assert signal.confidence == 0.95


def test_403_without_cf_is_access_denied_not_cloudflare() -> None:
    signal = detect_block(CF_403_HTML, 403, {"server": "nginx"})
    assert signal.kind == "access_denied"
    assert signal.recommended_escalation == "proxy"
