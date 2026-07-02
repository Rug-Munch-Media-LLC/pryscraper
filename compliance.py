"""Pry — Legal Compliance Engine.
Per-source compliance scorecard: robots.txt, ToS, GDPR/CCPA, jurisdiction."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import logging
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

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

# Known vendor block pages for TOS classification
TOS_INDICATORS = {
    "restrictive": [
        r"no scraping|no crawling|no automated",
        r"prohibited.*automated|automated.*prohibited",
        r"reverse engineer|decompile|disassemble",
        r"commercial use.*prohibited|not.*commercial use",
        r"rate limit|throttle|api limit",
        r"copyright.*all rights reserved",
        r"do not store|cache.*prohibited",
    ],
    "permissive": [
        r"open data|public data|freely available",
        r"creative commons|CC BY|CC0",
        r"api.*available|public.*api",
        r"attribution required",
        r"research.*permitted|academic.*use",
    ],
    "moderate": [
        r"personal use only|non-commercial only",
        r"attribution.*required|credit.*required",
        r"limited.*use|reasonable.*use",
        r"fair use|fair dealing",
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


async def check_robots_txt(url: str) -> dict[str, Any]:
    """Fetch and parse robots.txt, return crawl permissions for this URL."""
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    result: dict[str, Any] = {
        "robots_url": robots_url,
        "accessible": False,
        "crawl_allowed": True,
        "crawl_delay": 0,
        "disallowed_paths": [],
        "sitemaps": [],
        "error": None,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(robots_url, follow_redirects=True)
            if resp.status_code == 404:
                result["accessible"] = False
                result["crawl_allowed"] = True  # No robots.txt = no restrictions
                result["note"] = "No robots.txt found — no restrictions"
                return result
            if resp.status_code >= 400:
                result["accessible"] = False
                result["crawl_allowed"] = True
                result["note"] = f"robots.txt returned {resp.status_code}"
                return result

            result["accessible"] = True
            text = resp.text
            path = parsed.path or "/"

            # Parse disallowed paths
            current_agent = "*"
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("User-agent:"):
                    current_agent = line.split(":", 1)[1].strip()
                elif line.startswith("Disallow:"):
                    disallowed = line.split(":", 1)[1].strip()
                    if current_agent == "*" and disallowed:
                        result["disallowed_paths"].append(disallowed)
                elif line.startswith("Crawl-delay:"):
                    delay = line.split(":", 1)[1].strip()
                    if current_agent == "*" and delay.isdigit():
                        result["crawl_delay"] = int(delay)
                elif line.startswith("Sitemap:"):
                    sitemap = line.split(":", 1)[1].strip()
                    result["sitemaps"].append(sitemap)

            # Check if URL path is disallowed
            for disallowed in result["disallowed_paths"]:
                if path.startswith(disallowed):
                    result["crawl_allowed"] = False
                    result["matched_disallow"] = disallowed
                    break

    except Exception as e:
        result["error"] = str(e)
        result["crawl_allowed"] = True  # Fail open: assume allowed if can't check
        result["note"] = f"Could not fetch robots.txt: {str(e)[:100]}"

    return result


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
    if domain.endswith(".org") or domain.endswith(".net"):
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


def classify_tos(text: str) -> dict[str, Any]:
    """Classify Terms of Service as restrictive/permissive/moderate."""
    lower = text.lower()
    matches: dict[str, list[str]] = {"restrictive": [], "permissive": [], "moderate": []}

    for category, patterns in TOS_INDICATORS.items():
        for p in patterns:
            if re.search(p, lower):
                matches[category].append(p)

    # Determine overall classification
    restrictive_score = len(matches["restrictive"])
    permissive_score = len(matches["permissive"])
    moderate_score = len(matches["moderate"])

    if restrictive_score > permissive_score and restrictive_score > moderate_score:
        classification = "restrictive"
    elif permissive_score > restrictive_score and permissive_score >= moderate_score:
        classification = "permissive"
    else:
        classification = "moderate"

    return {
        "classification": classification,
        "confidence": "high"
        if (restrictive_score + permissive_score + moderate_score) >= 3
        else "medium",
        "matches": {k: len(v) for k, v in matches.items()},
        "note": _tos_note(classification),
    }


def _tos_note(classification: str) -> str:
    notes = {
        "restrictive": "Terms prohibit scraping or automated access. Legal review recommended.",
        "permissive": "Terms appear to allow data access. Verify specific clauses.",
        "moderate": "Terms have mixed signals. May allow limited non-commercial use.",
    }
    return notes.get(classification, "Unable to classify terms.")


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


async def run_compliance_check(url: str) -> dict[str, Any]:
    """Run full compliance check on a URL: robots.txt + jurisdiction + ToS + sensitive data."""
    # Fetch robots.txt
    robots = await check_robots_txt(url)

    # Fetch page content for ToS + sensitive data analysis
    html = ""
    tos_text = ""
    tos_url = ""
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": "PryCompliance/1.0 (compliance check)"},
            )
            if resp.is_success:
                html = resp.text
    except Exception:
        pass

    # Try to find and fetch ToS page
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    tos_paths = ["/terms", "/terms-of-service", "/tos", "/legal/terms", "/terms.html"]
    for path in tos_paths:
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                resp = await client.get(f"{base}{path}")
                if resp.is_success and len(resp.text) > 200:
                    tos_text = resp.text
                    tos_url = f"{base}{path}"
                    break
        except Exception:
            continue

    # Run all checks
    jurisdiction = detect_jurisdiction(url, html)
    tos_result = (
        classify_tos(tos_text)
        if tos_text
        else {
            "classification": "unknown",
            "confidence": "low",
            "matches": {},
            "note": "Could not locate Terms of Service page.",
        }
    )
    sensitive = (
        tag_sensitive_data(html)
        if html
        else {
            "has_pii": False,
            "has_financial": False,
            "has_contact": False,
            "has_health": False,
            "has_employment": False,
            "categories_present": [],
            "samples": {},
            "gdpr_relevance": "unknown",
        }
    )

    # Compute overall risk score
    risk_factors = 0
    risk_notes = []

    if robots.get("crawl_allowed") is False:
        risk_factors += 3
        risk_notes.append("robots.txt disallows crawling")

    if tos_result["classification"] == "restrictive":
        risk_factors += 3
        risk_notes.append("Terms of Service prohibit scraping")

    if jurisdiction.get("jurisdiction") == "eu" and sensitive.get("has_pii"):
        risk_factors += 2
        risk_notes.append("GDPR applies to personal data")

    if jurisdiction.get("jurisdiction") == "ca" and sensitive.get("has_pii"):
        risk_factors += 2
        risk_notes.append("CCPA applies to personal data")

    if sensitive.get("has_health"):
        risk_factors += 2
        risk_notes.append("HIPAA-protected health data detected")

    if sensitive.get("has_financial"):
        risk_factors += 1
        risk_notes.append("Financial data — additional compliance may apply")

    if risk_factors >= 5:
        risk_level = "red"
    elif risk_factors >= 2:
        risk_level = "yellow"
    else:
        risk_level = "green"

    return {
        "url": url,
        "risk_level": risk_level,
        "risk_score": risk_factors,
        "risk_notes": risk_notes,
        "checked_at": datetime.now(UTC).isoformat(),
        "robots_txt": {
            "accessible": robots["accessible"],
            "crawl_allowed": robots["crawl_allowed"],
            "crawl_delay": robots["crawl_delay"],
            "disallowed_paths": robots["disallowed_paths"],
            "sitemaps": robots["sitemaps"],
            "note": robots.get("note", ""),
        },
        "terms_of_service": {
            "found": bool(tos_url),
            "url": tos_url or "",
            "classification": tos_result["classification"],
            "confidence": tos_result["confidence"],
            "note": tos_result["note"],
        },
        "jurisdiction": {
            "tld": jurisdiction["tld"],
            "region": jurisdiction["jurisdiction"],
            "gdpr_signals": jurisdiction["gdpr_signals"],
            "ccpa_signals": jurisdiction["ccpa_signals"],
        },
        "sensitive_data": {
            "has_pii": sensitive["has_pii"],
            "has_financial": sensitive["has_financial"],
            "has_contact": sensitive["has_contact"],
            "has_health": sensitive["has_health"],
            "categories": sensitive["categories_present"],
            "gdpr_relevance": sensitive["gdpr_relevance"],
        },
        "recommendations": _generate_recommendations(risk_level, risk_notes, jurisdiction),
    }


def _generate_recommendations(
    risk_level: str, risk_notes: list[str], jurisdiction: dict[str, Any]
) -> list[str]:
    recs = []
    if risk_level == "red":
        recs.append("LEGAL REVIEW REQUIRED: Multiple high-risk factors detected.")
        recs.append("Do not scrape without written legal approval.")
    elif risk_level == "yellow":
        recs.append("Proceed with caution. Consider:")
        recs.append("- Rate-limit requests to respect robots.txt")
        recs.append("- Anonymize any PII before storage")
        recs.append("- Review Terms of Service for scraping clauses")

    if "GDPR" in str(risk_notes) or jurisdiction.get("jurisdiction") == "eu":
        recs.append(
            "GDPR compliance required: ensure lawful basis, data minimization, right to erasure."
        )

    if "CCPA" in str(risk_notes) or jurisdiction.get("jurisdiction") == "ca":
        recs.append("CCPA compliance required: allow opt-out, disclose data collection.")

    if not recs:
        recs.append("Low risk — proceed with standard scraping practices.")
        recs.append("Monitor for changes to robots.txt and Terms of Service.")

    return recs
