# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Tests for human-in-the-loop review workflow."""

from pry.actors.review import (
    REVIEW_STATUS,
    approve_review,
    get_review_queue,
    reject_review,
    submit_for_review,
)


def test_review_status_defined() -> None:
    assert "pending" in REVIEW_STATUS
    assert "approved" in REVIEW_STATUS
    assert "rejected" in REVIEW_STATUS


def test_submit_review() -> None:
    import asyncio

    result = asyncio.run(
        submit_for_review(
            data={"price": 999.99, "name": "Test"},
            extraction_url="https://example.com",
            confidence_score=0.5,
            flagged_fields=[{"field": "price", "issue": "Suspicious value"}],
        )
    )
    assert "id" in result
    assert result["status"] == "pending"
    assert result["confidence_score"] == 0.5
    assert len(result["flagged_fields"]) == 1


def test_submit_and_approve() -> None:
    import asyncio

    result = asyncio.run(
        submit_for_review(
            data={"name": "Test"},
            extraction_url="https://example.com",
        )
    )
    review_id = result["id"]
    approved = asyncio.run(approve_review(review_id, reviewer="test_user", notes="Looks good"))
    assert approved["status"] == "approved"
    assert approved["reviewed_by"] == "test_user"


def test_submit_and_reject() -> None:
    import asyncio

    result = asyncio.run(
        submit_for_review(
            data={"name": "Test"},
            extraction_url="https://example.com",
        )
    )
    review_id = result["id"]
    rejected = asyncio.run(reject_review(review_id, reviewer="test_user", notes="Bad data"))
    assert rejected["status"] == "rejected"
    assert rejected["review_notes"] == "Bad data"


def test_get_review_queue() -> None:
    import asyncio

    asyncio.run(submit_for_review(data={"a": 1}, extraction_url="https://example.com"))
    queue = get_review_queue()
    assert len(queue) >= 1
    assert "data" not in queue[0]  # Summary should not include full payload


def test_approve_nonexistent() -> None:
    import asyncio

    result = asyncio.run(approve_review("nonexistent-id"))
    assert "error" in result
