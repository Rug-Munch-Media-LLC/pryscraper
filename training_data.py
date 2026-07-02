"""Pry — AI Training Data Pipeline.
Per-record provenance, license classifier, clean room export, compliance reports."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import hashlib
import json
import logging
import os
import re
import uuid
from collections import defaultdict
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

TRAINING_DIR = Path(os.path.expanduser("~/.pry/training"))
TRAINING_DIR.mkdir(parents=True, exist_ok=True)

# ── License Classification ──

LICENSE_PATTERNS: dict[str, list[str]] = {
    "cc0": [
        r"cc0|creative commons zero|public domain",
        r"dedicated to the public domain",
        r"no rights reserved",
    ],
    "cc_by": [
        r"cc by|creative commons attribution",
        r"cc-by-4\.0|cc-by-3\.0|cc-by-2\.0",
    ],
    "cc_by_sa": [
        r"cc by-sa|creative commons attribution-sharealike",
        r"cc-by-sa-4\.0|cc-by-sa-3\.0",
    ],
    "mit": [
        r"mit license|permissive.*license|opensource.*mit",
        r"as-is.*without.*warranty",
    ],
    "apache": [
        r"apache.*2\.0|apache license",
        r"licensed under the apache",
    ],
    "gpl": [
        r"gpl|gnu general public|gpl-3\.0|gpl-2\.0",
        r"copyleft|same license",
    ],
    "proprietary": [
        r"all rights reserved|proprietary",
        r"commercial license|enterprise license",
        r"not for redistribution|no reproduction",
        r"copyright.*\d{4}.*all rights",
    ],
    "fair_use": [
        r"fair use|fair dealing|academic use",
        r"research purposes|educational use",
        r"personal use only",
    ],
}

LICENSE_TIERS: dict[str, str] = {
    "cc0": "permissive",
    "cc_by": "permissive",
    "cc_by_sa": "permissive",
    "mit": "permissive",
    "apache": "permissive",
    "gpl": "copyleft",
    "proprietary": "restrictive",
    "fair_use": "conditional",
    "unknown": "unknown",
}


def classify_license(text: str) -> dict[str, Any]:
    """Classify the license of scraped content based on text analysis."""
    lower = text.lower()
    matches: dict[str, list[str]] = {}

    for license_name, patterns in LICENSE_PATTERNS.items():
        found = []
        for p in patterns:
            m = re.findall(p, lower)
            if m:
                found.extend(m)
        if found:
            matches[license_name] = found

    if not matches:
        return {
            "license": "unknown",
            "tier": "unknown",
            "confidence": "low",
            "note": "No license indicators found",
        }

    # Take the most restrictive license found
    priority = ["proprietary", "gpl", "cc_by_sa", "cc_by", "mit", "apache", "cc0", "fair_use"]
    best = "unknown"
    for license_name in priority:
        if license_name in matches:
            best = license_name
            break

    return {
        "license": best,
        "tier": LICENSE_TIERS.get(best, "unknown"),
        "confidence": "high" if len(matches[best]) >= 2 else "medium",
        "matched_indicators": {k: len(v) for k, v in matches.items()},
        "note": f"Classified as {best} ({LICENSE_TIERS.get(best, 'unknown')})",
    }


# ── PII / Copyright Stripping (Clean Room) ──

PII_PATTERNS = {
    "email": r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b",
    "phone": r"\b\+?\d{1,3}[-.]?\d{3,4}[-.]?\d{4}\b",
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "credit_card": r"\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b",
    "ip_address": r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
    "full_name": r"\b[A-Z][a-z]+ [A-Z][a-z]+\b",  # Rough: catches many false positives
}

COPYRIGHT_PATTERNS = [
    r"(?:copyright|©)\s*(?:\d{4}[-\d{4}]?)?\s*(?:by\s+)?[\w\s,]+?(?:\n|\.|$)",
    r"all rights reserved",
    r"this (?:work|content|document|article).*?(?:protected|licensed|copyright)",
]


def strip_pii(text: str, preserve_names: bool = False) -> tuple[str, dict[str, int]]:
    """Strip personally identifiable information from text.

    Returns (cleaned_text, stats) where stats shows what was removed.
    """
    stats: dict[str, int] = defaultdict(int)
    cleaned = text

    for pii_type, pattern in PII_PATTERNS.items():
        if pii_type == "full_name" and preserve_names:
            continue
        matches = re.findall(pattern, cleaned)
        if matches:
            stats[pii_type] = len(matches)
            cleaned = re.sub(pattern, f"[{pii_type.upper()}_REDACTED]", cleaned)

    return cleaned, dict(stats)


def strip_copyright_verbatim(text: str, min_block_length: int = 50) -> tuple[str, dict[str, Any]]:
    """Strip near-verbatim copyright content from text.

    Removes blocks that match copyright patterns and long verbatim quotes.
    """
    stats: dict[str, Any] = {"blocks_removed": 0, "total_chars_removed": 0}
    cleaned = text

    for pattern in COPYRIGHT_PATTERNS:
        matches = list(re.finditer(pattern, cleaned, re.IGNORECASE | re.MULTILINE))
        if matches:
            for m in matches:
                block = m.group(0)
                if len(block) >= min_block_length:
                    stats["blocks_removed"] += 1
                    stats["total_chars_removed"] += len(block)
            cleaned = re.sub(
                pattern, "[COPYRIGHT_NOTICE_REDACTED]", cleaned, flags=re.IGNORECASE | re.MULTILINE
            )

    return cleaned, stats


# ── Provenance Tracking ──


def create_provenance_record(
    url: str,
    content_hash: str,
    extraction_method: str = "scrape",
    extraction_config: dict[str, Any] | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Create a provenance record for a piece of training data.

    Tracks: source URL, fetch timestamp, extraction method, content hash,
    and processing pipeline.
    """
    return {
        "record_id": uuid.uuid4().hex[:16],
        "source_url": url,
        "source_domain": url.split("/")[2] if "//" in url else url,
        "fetch_timestamp": timestamp or datetime.now(UTC).isoformat(),
        "content_hash": content_hash,
        "extraction_method": extraction_method,
        "extraction_config": extraction_config or {},
        "pipeline_version": "3.0.0",
    }


# ── Dataset Export ──


def export_training_dataset(
    records: list[dict[str, Any]],
    format: Literal["jsonl", "parquet", "huggingface"] = "jsonl",
    clean_room: bool = True,
    strip_names: bool = False,
) -> dict[str, Any]:
    """Export a clean training dataset with provenance and compliance.

    Args:
        records: List of records (each should have "content", "metadata", "url")
        format: Export format
        clean_room: Strip PII and copyright verbatim text
        strip_names: Also strip full names (default: preserve)

    Returns export metadata and file path.
    """
    dataset_id = uuid.uuid4().hex[:8]
    dataset_dir = TRAINING_DIR / dataset_id
    dataset_dir.mkdir(parents=True, exist_ok=True)

    export_records = []
    total_pii_removed: dict[str, int] = defaultdict(int)
    total_copyright_removed = 0
    for i, record in enumerate(records):
        content = record.get("content") or record.get("text") or record.get("body", "")
        url = record.get("url") or record.get("source", "")
        metadata = record.get("metadata", {})
        extraction_method = record.get("extraction_method", "scrape")

        provenance = create_provenance_record(
            url=url,
            content_hash=hashlib.sha256(content.encode()).hexdigest()[:32],
            extraction_method=extraction_method,
        )

        export_record = {
            "id": f"{dataset_id}_{i:06d}",
            "provenance": provenance,
            "metadata": metadata,
        }

        if clean_room:
            # Strip PII
            cleaned_content, pii_stats = strip_pii(content, preserve_names=not strip_names)
            for k, v in pii_stats.items():
                total_pii_removed[k] += v

            # Strip copyright
            cleaned_content, copyright_stats = strip_copyright_verbatim(cleaned_content)
            total_copyright_removed += copyright_stats["blocks_removed"]

            export_record["content"] = cleaned_content
            export_record["cleaning_applied"] = {
                "pii_removed": bool(pii_stats),
                "copyright_stripped": copyright_stats["blocks_removed"] > 0,
                "pii_categories": list(pii_stats.keys()),
            }
        else:
            export_record["content"] = content
            export_record["cleaning_applied"] = {"pii_removed": False, "copyright_stripped": False}

        export_records.append(export_record)

    # Write export file
    if format == "jsonl":
        export_path = dataset_dir / f"dataset_{dataset_id}.jsonl"
        try:
            with open(export_path, "w") as f:
                for rec in export_records:
                    f.write(json.dumps(rec) + "\n")
        except OSError as e:
            return {"success": False, "error": str(e)}

    manifest = {
        "dataset_id": dataset_id,
        "format": format,
        "created_at": datetime.now(UTC).isoformat(),
        "total_records": len(records),
        "clean_room_applied": clean_room,
        "pii_removed": dict(total_pii_removed),
        "copyright_blocks_removed": total_copyright_removed,
        "provenance_tracked": True,
        "license_classification": "pending",  # Run classify on first record
    }

    manifest_path = dataset_dir / "manifest.json"
    with suppress(OSError):
        manifest_path.write_text(json.dumps(manifest, indent=2))

    return {
        "success": True,
        "dataset_id": dataset_id,
        "path": str(export_path) if format == "jsonl" else str(dataset_dir),
        "record_count": len(records),
        "manifest": manifest,
    }


def generate_compliance_report(dataset_id: str) -> dict[str, Any]:
    """Generate a compliance report PDF for a training dataset."""
    dataset_dir = TRAINING_DIR / dataset_id
    manifest_path = dataset_dir / "manifest.json"

    if not manifest_path.exists():
        return {"error": f"Dataset not found: {dataset_id}"}

    try:
        manifest = json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {"error": "Could not read manifest"}

    # Count records with provenance
    record_count = manifest.get("total_records", 0)
    pii_removed = manifest.get("pii_removed", {})
    copyright_removed = manifest.get("copyright_blocks_removed", 0)

    report_lines = [
        "=" * 60,
        "AI TRAINING DATA COMPLIANCE REPORT",
        "=" * 60,
        "",
        f"Dataset ID: {dataset_id}",
        f"Generated: {manifest.get('created_at', 'Unknown')}",
        f"Format: {manifest.get('format', 'jsonl')}",
        "",
        "\u2500\u2500 DATA SOURCING \u2500\u2500",
        f"Total Records: {record_count}",
        f"Provenance Tracked: {manifest.get('provenance_tracked', False)}",
        "",
        "\u2500\u2500 CLEAN ROOM PROCESSING \u2500\u2500",
        f"Clean Room Applied: {manifest.get('clean_room_applied', False)}",
        f"PII Removed: {pii_removed}",
        f"Copyright Blocks Stripped: {copyright_removed}",
        "",
        "\u2500\u2500 LICENSE ANALYSIS \u2500\u2500",
        f"Classification: {manifest.get('license_classification', 'Pending')}",
        "",
        "\u2500\u2500 RECOMMENDATIONS \u2500\u2500",
        "\u2022 Verify license classification for all source domains",
        "\u2022 Ensure lawful basis for data collection (GDPR Art. 6)",
        "\u2022 Document data retention and erasure policy",
        "\u2022 Review if training use falls under fair use/fair dealing",
        "",
        "This report was auto-generated by Pry Training Data Pipeline v3.0.0",
        "=" * 60,
    ]

    report_text = "\n".join(report_lines)
    report_path = dataset_dir / "compliance_report.txt"

    with suppress(OSError):
        report_path.write_text(report_text)

    return {
        "success": True,
        "dataset_id": dataset_id,
        "report": report_text,
        "path": str(report_path),
    }
