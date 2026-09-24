"""Canonical record and scalar normalization for firmographics."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import re
from typing import Any


def _empty_firmographics(company: str) -> dict[str, Any]:
    """Return the canonical empty firmographics record."""
    return {
        "name": company,
        "headcount": None,
        "funding": None,
        "total_funding": None,
        "tech_stack": [],
        "industry": None,
        "hiring_openings": 0,
        "linkedin_url": None,
        "website": None,
    }


def _normalize_slug(company: str) -> str:
    """Convert a company name to a domain/job-board slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", company.lower()).strip("-")
    return slug or "company"


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_money(value: Any) -> int | None:
    """Coerce a JSON money value (number or ``$12M`` string) to int USD."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    multiplier = 1
    upper = text.upper()
    if upper.endswith("B"):
        multiplier, upper = 1_000_000_000, upper[:-1]
    elif upper.endswith("M"):
        multiplier, upper = 1_000_000, upper[:-1]
    elif upper.endswith("K"):
        multiplier, upper = 1_000, upper[:-1]
    digits = re.sub(r"[^0-9.]", "", upper)
    parts = digits.split(".")
    if not digits or len(parts) > 2 or not all(part.isdecimal() for part in parts):
        return None
    return int(float(digits) * multiplier)
