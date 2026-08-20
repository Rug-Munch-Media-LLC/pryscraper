"""Pry — Review router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body

from deps import scraper
from errors import NotFoundError, ScrapeError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Review"])


@router.post("/v1/review/submit", tags=["Review"], summary="Submit extracted data for human review")
async def review_submit(
    data: dict[str, Any] = Body(...),
    url: str = Body(...),
    schema_name: str | None = Body(None),
    confidence_score: float = Body(0.0),
    flagged_fields: list[dict[str, Any]] | None = Body(None),
) -> dict[str, Any]:
    """Submit extracted data for human review before delivery.

    Use this when extraction confidence is low or anomalies were detected.
    Data will be held in the review queue until approved or rejected.
    """
    from review import submit_for_review

    result = await submit_for_review(
        data=data,
        extraction_url=url,
        schema_name=schema_name,
        confidence_score=confidence_score,
        flagged_fields=flagged_fields,
    )
    return {"success": True, "data": result}


@router.post("/v1/review/{review_id}/approve", tags=["Review"], summary="Approve a review item")
async def review_approve(
    review_id: str,
    reviewer: str = Body("api"),
    notes: str = Body(""),
) -> dict[str, Any]:
    """Approve a review item, allowing data to proceed to delivery."""
    from review import approve_review

    result = await approve_review(review_id, reviewer, notes)
    if "error" in result:
        raise NotFoundError(result["error"])
    return {"success": True, "data": result}


@router.post("/v1/review/{review_id}/reject", tags=["Review"], summary="Reject a review item")
async def review_reject(
    review_id: str,
    reviewer: str = Body("api"),
    notes: str = Body(""),
) -> dict[str, Any]:
    """Reject a review item, blocking data delivery."""
    from review import reject_review

    result = await reject_review(review_id, reviewer, notes)
    if "error" in result:
        raise NotFoundError(result["error"])
    return {"success": True, "data": result}


@router.get("/v1/reviews", tags=["Review"], summary="List reviews in the queue")
async def list_reviews(status: str | None = None) -> dict[str, Any]:
    """List reviews, optionally filtered by status (pending/approved/rejected)."""
    from review import get_review_queue

    reviews = get_review_queue(status)
    return {"success": True, "data": {"reviews": reviews, "total": len(reviews)}}


@router.get("/v1/review/{review_id}", tags=["Review"], summary="Get review details")
async def get_review(review_id: str) -> dict[str, Any]:
    """Get full details of a review item including the data payload."""
    from review import get_review_detail

    result = get_review_detail(review_id)
    if not result:
        raise NotFoundError(f"Review not found: {review_id}")
    return {"success": True, "data": result}


@router.post(
    "/v1/extract-with-review",
    tags=["Review"],
    summary="Extract with automatic human review routing",
)
async def extract_with_review(
    url: str = Body(...),
    schema: dict[str, Any] | None = Body(None),
    expected_types: dict[str, str] | None = Body(None),
    slack_webhook: str = Body(""),
    auto_approve_threshold: float = Body(0.8),
    auto_reject_threshold: float = Body(0.2),
) -> dict[str, Any]:
    """Extract data with automatic quality check and human review routing.

    High-confidence results are auto-approved.
    Low-confidence results are auto-rejected.
    Medium-confidence results go to the human review queue with Slack notification.
    """
    from quality import run_quality_check
    from review import auto_review_threshold

    # Scrape
    scrape_result = await scraper.scrape(url, {"bypass_cloudflare": True})
    if scrape_result.get("status") != "ok":
        raise ScrapeError(scrape_result.get("error") or "Scrape failed")

    data = scrape_result

    # Quality check
    quality = await run_quality_check(
        url=url,
        data=data,
        schema=schema,
        expected_types=None,
    )

    # Auto-route
    decision = await auto_review_threshold(
        data=data,
        extraction_url=url,
        quality_result=quality,
        slack_webhook=slack_webhook,
        auto_approve_threshold=auto_approve_threshold,
        auto_reject_threshold=auto_reject_threshold,
    )

    return {
        "success": True,
        "data": {
            "decision": decision,
            "quality": {k: v for k, v in quality.items() if k != "url"},
        },
    }
