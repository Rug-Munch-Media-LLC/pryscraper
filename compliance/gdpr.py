"""Pry — GDPR / data-subject compliance logic.

Sensitive-data pattern detection and jurisdiction detection for
GDPR/CCPA/LGPD applicability.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import re
from typing import Any
from urllib.parse import urlparse

# GDPR/CCPA sensitive data patterns
SENSITIVE_DATA_PATTERNS = {
    "personally_identifiable": [
        r"\b[A-Z][a-z]+ [A-Z][a-z]+\b",  # Full names
        r"\b\d{3}-\d{2}-\d{4}\b",  # SSN
        r"\b\d{9}\b",  # SSN compact
        r"\b\d{1,2}/\d{1,2}/\d{4}\b",  # Dates
    ],
    "financial": [
        r"\$\d+(?:,\d{3})*(?:\.\d{2})?",  # Dollar amounts
        r"\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b",  # Credit cards
        r"\b(?:invoice|payment|billing|purchase)\b",
    ],
    "contact": [
        r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b",  # Emails
        r"\b\+?\d{1,3}[-.]?\d{3,4}[-.]?\d{4}\b",  # Phones
        r"\b\d{5}(?:-\d{4})?\b",  # ZIP codes
    ],
    "health": [
        r"\b(?:diagnosis|patient|medical|treatment|healthcare)\b",
        r"\b(?:HIPAA|HIPPA|PHI)\b",
    ],
    "employment": [
        r"\b(?:salary|wage|compensation|payroll|bonus)\b",
        r"\b(?:resume|CV|applicant|candidate)\b",
    ],
}

# Jurisdiction detection by TLD and language patterns
JURISDICTION_MAP = {
    ".eu": "eu",
    ".de": "eu",
    ".fr": "eu",
    ".nl": "eu",
    ".it": "eu",
    ".es": "eu",
    ".pl": "eu",
    ".se": "eu",
    ".dk": "eu",
    ".fi": "eu",
    ".at": "eu",
    ".be": "eu",
    ".ie": "eu",
    ".pt": "eu",
    ".gr": "eu",
    ".cz": "eu",
    ".hu": "eu",
    ".ro": "eu",
    ".bg": "eu",
    ".sk": "eu",
    ".si": "eu",
    ".lt": "eu",
    ".lv": "eu",
    ".ee": "eu",
    ".hr": "eu",
    ".mt": "eu",
    ".lu": "eu",
    ".cy": "eu",
    ".co.uk": "eu",
    ".uk": "eu",
    ".ch": "other",
    ".no": "other",
    ".is": "other",
    ".ca": "ca",
    ".com.au": "au",
    ".jp": "jp",
    ".cn": "cn",
    ".in": "in",
}


def detect_jurisdiction(url: str, html: str = "") -> dict[str, Any]:
    """Detect likely legal jurisdiction based on TLD and content signals."""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    tld_found = "unknown"

    # Check TLD map
    for tld, jurisdiction in sorted(JURISDICTION_MAP.items(), key=lambda x: -len(x[0])):
        if domain.endswith(tld):
            tld_found = jurisdiction
            break
    if domain.endswith(".com"):
        tld_found = "us"
    if domain.endswith((".org", ".net")):
        tld_found = "unknown"

    # Check HTML for GDPR/CCPA signals
    signals = {"gdpr": False, "ccpa": False, "lgpd": False}
    if html:
        lower = html.lower()
        signals["gdpr"] = bool(
            re.search(r"gdpr|general data protection|data protection regulation", lower)
        )
        signals["ccpa"] = bool(
            re.search(r"ccpa|california consumer privacy|california privacy rights", lower)
        )
        signals["lgpd"] = bool(re.search(r"lgpd|lei geral de prote", lower))

    return {
        "tld": domain.split(".")[-1] if "." in domain else "unknown",
        "jurisdiction": tld_found,
        "gdpr_signals": signals["gdpr"],
        "ccpa_signals": signals["ccpa"],
        "lgpd_signals": signals["lgpd"],
    }


def tag_sensitive_data(html: str) -> dict[str, Any]:
    """Tag GDPR/CCPA sensitive data categories present in content."""
    found: dict[str, list[str]] = {}
    for category, patterns in SENSITIVE_DATA_PATTERNS.items():
        matches = []
        for p in patterns:
            m = re.findall(p, html)
            if m:
                matches.extend(m[:5])  # Limit to 5 samples per pattern
        if matches:
            found[category] = matches

    return {
        "has_pii": "personally_identifiable" in found,
        "has_financial": "financial" in found,
        "has_contact": "contact" in found,
        "has_health": "health" in found,
        "has_employment": "employment" in found,
        "categories_present": list(found.keys()),
        "samples": {k: v[:3] for k, v in found.items()},
        "gdpr_relevance": "high"
        if any(c in found for c in ["personally_identifiable", "financial", "health"])
        else "medium"
        if "contact" in found
        else "low",
    }


__all__ = [
    "JURISDICTION_MAP",
    "SENSITIVE_DATA_PATTERNS",
    "detect_jurisdiction",
    "tag_sensitive_data",
]
