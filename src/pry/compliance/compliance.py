"""Pry — Legal Compliance Engine (facade).

Thin re-export facade over the ``compliance`` package. Kept for backward
compatibility: existing ``from compliance import X`` imports keep working.

Implementation lives in:
  - ``compliance.gdpr`` — GDPR/data-subject logic
  - ``compliance.policy`` — scraping policy / robots / terms checks
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from compliance.gdpr import (
    JURISDICTION_MAP,
    SENSITIVE_DATA_PATTERNS,
    detect_jurisdiction,
    tag_sensitive_data,
)
from compliance.policy import (
    TOS_INDICATORS,
    check_robots_txt,
    classify_tos,
    run_compliance_check,
)

__all__ = [
    "JURISDICTION_MAP",
    "SENSITIVE_DATA_PATTERNS",
    "TOS_INDICATORS",
    "check_robots_txt",
    "classify_tos",
    "detect_jurisdiction",
    "run_compliance_check",
    "tag_sensitive_data",
]
