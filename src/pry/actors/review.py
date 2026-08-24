"""Pry — Human-in-the-Loop Validation Workflow.
Routes low-confidence extractions to human review before delivery."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
import json
import logging
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from pry.core.paths import PRY_DATA_DIR

logger = logging.getLogger(__name__)

REVIEW_DIR = PRY_DATA_DIR / "reviews"
REVIEW_DIR.mkdir(parents=True, exist_ok=True)

# Status enum for review items
REVIEW_STATUS = ["pending", "approved", "rejected", "escalated"]


def _review_path(review_id: str) -> Path:
    return REVIEW_DIR / f"{review_id}.json"


async def submit_for_review(
    data: dict[str, Any],
    extraction_url: str,
    schema_name: str | None = None,
    confidence_score: float = 0.0,
    flagged_fields: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Submit extracted data for human review.

    Args:
        data: The extracted data that needs review
        extraction_url: The source URL
        schema_name: The schema/vertical used for extraction
        confidence_score: Overall confidence score (0-1)
        flagged_fields: Specific fields with issues
        metadata: Additional context

    Returns the review item with a unique ID.
    """
    review_id = uuid.uuid4().hex[:12]
    review_item = {
        "id": review_id,
        "status": "pending",
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
        "extraction_url": extraction_url,
        "schema_name": schema_name or "unknown",
        "confidence_score": round(confidence_score, 2),
        "flagged_fields": flagged_fields or [],
        "data": data,
        "metadata": metadata or {},
        "reviewed_by": None,
        "reviewed_at": None,
        "review_notes": "",
    }
    path = _review_path(review_id)
    try:
        path.write_text(json.dumps(review_item, indent=2))
        logger.info(
            "review_submitted",
            extra={
                "review_id": review_id,
                "confidence": confidence_score,
                "flagged_fields": len(flagged_fields or []),
            },
        )
        return review_item
    except OSError as e:
        logger.exception("review_save_failed")
        return {"error": str(e)}


async def approve_review(
    review_id: str,
    reviewer: str = "system",
    notes: str = "",
) -> dict[str, Any]:
    """Approve a review item, allowing data to proceed to delivery."""
    path = _review_path(review_id)
    if not path.exists():
        return {"error": f"Review not found: {review_id}"}

    try:
        item = cast("dict[str, Any]", json.loads(path.read_text()))
        item["status"] = "approved"
        item["reviewed_by"] = reviewer
        item["reviewed_at"] = datetime.now(UTC).isoformat()
        item["review_notes"] = notes
        item["updated_at"] = datetime.now(UTC).isoformat()
        path.write_text(json.dumps(item, indent=2))
        logger.info("review_approved", extra={"review_id": review_id, "reviewer": reviewer})
        return item
    except (json.JSONDecodeError, OSError) as e:
        return {"error": str(e)}


async def reject_review(
    review_id: str,
    reviewer: str = "system",
    notes: str = "",
) -> dict[str, Any]:
    """Reject a review item, blocking data delivery."""
    path = _review_path(review_id)
    if not path.exists():
        return {"error": f"Review not found: {review_id}"}

    try:
        item = cast("dict[str, Any]", json.loads(path.read_text()))
        item["status"] = "rejected"
        item["reviewed_by"] = reviewer
        item["reviewed_at"] = datetime.now(UTC).isoformat()
        item["review_notes"] = notes
        item["updated_at"] = datetime.now(UTC).isoformat()
        path.write_text(json.dumps(item, indent=2))
        logger.info("review_rejected", extra={"review_id": review_id, "reviewer": reviewer})
        return item
    except (json.JSONDecodeError, OSError) as e:
        return {"error": str(e)}


def get_review_queue(status: str | None = None) -> list[dict[str, Any]]:
    """Get the review queue, optionally filtered by status."""
    reviews = []
    for path in sorted(REVIEW_DIR.glob("*.json"), key=os.path.getmtime, reverse=True):
        try:
            item = json.loads(path.read_text())
            if status and item.get("status") != status:
                continue
            # Return summary without full data payload
            reviews.append(
                {
                    "id": item["id"],
                    "status": item["status"],
                    "created_at": item["created_at"],
                    "extraction_url": item["extraction_url"],
                    "schema_name": item["schema_name"],
                    "confidence_score": item["confidence_score"],
                    "flagged_fields": item["flagged_fields"],
                    "flagged_field_count": len(item.get("flagged_fields", [])),
                    "reviewed_by": item.get("reviewed_by"),
                    "reviewed_at": item.get("reviewed_at"),
                }
            )
        except (json.JSONDecodeError, OSError):
            continue
    return reviews


def get_review_detail(review_id: str) -> dict[str, Any] | None:
    """Get full review item detail including data."""
    path = _review_path(review_id)
    if not path.exists():
        return None
    try:
        return cast("dict[str, Any]", json.loads(path.read_text()))
    except (json.JSONDecodeError, OSError):
        return None


async def notify_slack_review(
    webhook_url: str,
    review_id: str,
    extraction_url: str,
    confidence_score: float,
    flagged_fields: list[dict[str, Any]],
) -> dict[str, Any]:
    """Send a Slack notification for a pending review."""
    from pry.commerce.destinations import write_to_slack

    field_details = "\n".join(
        f"• {f.get('field', 'unknown')}: {f.get('issue', 'flagged')}"
        for f in (flagged_fields or [])[:5]
    )
    message = (
        f"*New Review Requested*\n"
        f"• *Review ID:* `{review_id}`\n"
        f"• *URL:* {extraction_url}\n"
        f"• *Confidence:* {confidence_score}\n"
        f"• *Flagged Fields:*\n{field_details}\n\n"
        f"Approve: `POST /v1/review/{review_id}/approve`\n"
        f"Reject: `POST /v1/review/{review_id}/reject`"
    )
    return await write_to_slack(
        webhook_url, message, title="Pry — Human Review Required", color="#ffa500"
    )


async def auto_review_threshold(
    data: dict[str, Any],
    extraction_url: str,
    quality_result: dict[str, Any],
    slack_webhook: str = "",
    auto_approve_threshold: float = 0.8,
    auto_reject_threshold: float = 0.2,
) -> dict[str, Any]:
    """Automatically route extraction based on quality scores.

    - Above auto_approve_threshold: auto-approve, deliver immediately
    - Below auto_reject_threshold: auto-reject, block delivery
    - In between: route to human review
    """
    quality_score = quality_result.get("quality_score", 50) / 100.0
    anomalies = quality_result.get("anomalies", [])
    critical_anomalies = quality_result.get("critical_anomalies", 0)

    # Adjust score down for critical anomalies
    if critical_anomalies > 0:
        quality_score *= max(0.1, 1.0 - (critical_anomalies * 0.3))

    flagged_fields = [
        {
            "field": a.get("field", "unknown"),
            "issue": a.get("message", "Flagged"),
            "severity": a.get("severity", "medium"),
        }
        for a in anomalies[:10]
    ]

    if quality_score >= auto_approve_threshold:
        return {
            "decision": "approved",
            "reason": f"Quality score {quality_score:.0%} above auto-approve threshold",
            "review_id": None,
        }

    if quality_score < auto_reject_threshold:
        return {
            "decision": "rejected",
            "reason": f"Quality score {quality_score:.0%} below auto-reject threshold",
            "review_id": None,
        }

    # Submit for human review
    review = await submit_for_review(
        data=data,
        extraction_url=extraction_url,
        confidence_score=quality_score,
        flagged_fields=flagged_fields,
    )
    review_id = review.get("id", "")

    # Notify Slack if configured
    if slack_webhook and review_id:
        await notify_slack_review(
            slack_webhook, review_id, extraction_url, quality_score, flagged_fields
        )

    return {
        "decision": "review_required",
        "reason": f"Quality score {quality_score:.0%} needs human review",
        "review_id": review_id,
        "review": review,
    }
