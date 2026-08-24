# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for GDPR compliance portal."""

from pry.compliance.gdpr import (
    check_consent,
    get_retention_policy,
    process_deletion,
    record_consent,
    revoke_consent,
)


def test_record_consent() -> None:
    import asyncio

    result = asyncio.run(record_consent("user@example.com", "data_collection", True))
    assert result["success"] is True
    assert result["consent"]["consent_given"] is True


def test_check_consent_given() -> None:
    import asyncio

    asyncio.run(record_consent("check@example.com", "data_collection", True))
    result = check_consent("check@example.com", "data_collection")
    assert result["consent_given"] is True
    assert result["valid"] is True


def test_check_consent_not_given() -> None:
    result = check_consent("nonexistent@example.com", "data_collection")
    assert result["consent_given"] is False


def test_revoke_consent() -> None:
    import asyncio

    asyncio.run(record_consent("revoke@example.com", "data_collection", True))
    result = revoke_consent("revoke@example.com", "data_collection")
    assert result["success"] is True
    # Verify revocation
    check = check_consent("revoke@example.com", "data_collection")
    assert check["consent_given"] is False


def test_process_deletion() -> None:
    import asyncio

    asyncio.run(record_consent("delete@example.com", "data_collection", True))
    result = process_deletion("delete@example.com")
    assert result["success"] is True
    # Verify consent gone
    check = check_consent("delete@example.com", "data_collection")
    assert check["consent_given"] is False


def test_retention_policy() -> None:
    policy = get_retention_policy()
    assert "consent_records" in policy
    assert "quality_history" in policy
