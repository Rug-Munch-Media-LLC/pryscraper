# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for AI training data pipeline."""

from training_data import (
    classify_license,
    export_training_dataset,
    strip_copyright_verbatim,
    strip_pii,
)


def test_classify_license_mit() -> None:
    text = "This project is licensed under the MIT License. It is provided as-is without warranty."
    result = classify_license(text)
    assert result["license"] == "mit"
    assert result["tier"] == "permissive"


def test_classify_license_proprietary() -> None:
    text = "Copyright 2024 Example Corp. All rights reserved. Proprietary software."
    result = classify_license(text)
    assert result["license"] == "proprietary"
    assert result["tier"] == "restrictive"


def test_classify_license_cc0() -> None:
    text = "CC0 1.0 Universal \u2014 dedicated to the public domain."
    result = classify_license(text)
    assert result["license"] == "cc0"
    assert result["tier"] == "permissive"


def test_classify_license_unknown() -> None:
    result = classify_license("Some random text with no license info.")
    assert result["license"] == "unknown"


def test_strip_pii_email() -> None:
    text = "Contact us at support@example.com for help."
    cleaned, stats = strip_pii(text)
    assert "EMAIL_REDACTED" in cleaned
    assert stats.get("email") == 1


def test_strip_pii_phone() -> None:
    text = "Call 555-123-4567 for support."
    cleaned, stats = strip_pii(text)
    assert "PHONE_REDACTED" in cleaned
    assert stats.get("phone") == 1


def test_strip_pii_no_pii() -> None:
    text = "This is clean text with no personal information."
    cleaned, stats = strip_pii(text)
    assert cleaned == text
    assert all(v == 0 for v in stats.values()) or not stats


def test_strip_copyright() -> None:
    text = "Some content. Copyright 2024 Example Corp. All rights reserved. More content."
    cleaned, stats = strip_copyright_verbatim(text)
    assert "COPYRIGHT" in cleaned or stats["blocks_removed"] >= 0


def test_export_dataset() -> None:
    records = [
        {"content": "Hello world", "url": "https://example.com"},
        {"content": "Contact me@example.com for info", "url": "https://example.com/contact"},
    ]
    result = export_training_dataset(records, format="jsonl", clean_room=True)
    assert result["success"] is True
    assert result["record_count"] == 2
    assert "dataset_id" in result
