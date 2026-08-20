"""Pry — Training router (remaining api.py routes).

Auto-extracted from api.py during the router-split refactor.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body

from errors import NotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Training"])


@router.post(
    "/v1/training/classify-license",
    tags=["Training"],
    summary="Classify content license for AI training",
)
async def classify_license_endpoint(text: str = Body(...)) -> dict[str, Any]:
    """Classify the license of scraped content for AI training compliance.

    Returns license type (CC0, CC-BY, MIT, Apache, GPL, Proprietary, Fair Use),
    tier (permissive/copyleft/restrictive/conditional), and confidence.
    """
    from training_data import classify_license

    result = classify_license(text)
    return {"success": True, "data": result}


@router.post(
    "/v1/training/clean", tags=["Training"], summary="Strip PII and copyright from content"
)
async def clean_content(
    text: str = Body(...),
    strip_names: bool = Body(False),
    strip_copyright: bool = Body(True),
) -> dict[str, Any]:
    """Strip PII and copyright content for AI training clean room.

    Removes emails, phones, SSNs, credit cards, IPs, and (optionally) names.
    Also strips copyright notices and near-verbatim copyright content.
    """
    from training_data import strip_copyright_verbatim, strip_pii

    cleaned, pii_stats = strip_pii(text, preserve_names=not strip_names)
    copyright_stats = {"blocks_removed": 0, "total_chars_removed": 0}

    if strip_copyright:
        cleaned, copyright_stats = strip_copyright_verbatim(cleaned)

    return {
        "success": True,
        "data": {
            "original_length": len(text),
            "cleaned_length": len(cleaned),
            "pii_removed": pii_stats,
            "copyright_blocks_removed": copyright_stats["blocks_removed"],
            "copyright_chars_removed": copyright_stats["total_chars_removed"],
            "cleaned_content": cleaned[:5000] if len(cleaned) > 5000 else cleaned,
            "truncated": len(cleaned) > 5000,
        },
    }


@router.post(
    "/v1/training/export",
    tags=["Training"],
    summary="Export a clean AI training dataset",
)
async def export_dataset(
    records: list[dict[str, Any]] = Body(...),
    output_format: str = Body("jsonl"),
    clean_room: bool = Body(True),
    strip_names: bool = Body(False),
) -> dict[str, Any]:
    """Export scraped content as a clean AI training dataset.

    Each record should have: content, url, and optional metadata.

    Features:
    - Per-record provenance tracking (source URL, timestamp, extraction method)
    - PII stripping (email, phone, SSN, CC, IP)
    - Copyright verbatim text removal
    - License classification
    - Compliance report generation
    """
    from training_data import export_training_dataset

    result = export_training_dataset(
        records=records,
        format=output_format,  # type: ignore
        clean_room=clean_room,
        strip_names=strip_names,
    )
    return {"success": result["success"], "data": result}


@router.get(
    "/v1/training/compliance/{dataset_id}",
    tags=["Training"],
    summary="Generate compliance report for a dataset",
)
async def compliance_report(dataset_id: str) -> dict[str, Any]:
    """Generate a compliance report for an exported training dataset.

    Report includes: data provenance, PII/copyright removal stats,
    license classification, and legal recommendations.
    """
    from training_data import generate_compliance_report

    result = generate_compliance_report(dataset_id)
    if "error" in result:
        raise NotFoundError(result["error"])
    return {"success": True, "data": result}
