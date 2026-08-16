"""Pry — Scraping policy checks: robots.txt, Terms of Service, compliance scorecard.

Hosts the full ``run_compliance_check`` orchestrator used by routers and
pipelines, plus the robots.txt and ToS classification primitives.
"""

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

from compliance.gdpr import detect_jurisdiction, tag_sensitive_data

logger = logging.getLogger(__name__)

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

    except (httpx.HTTPError, httpx.RequestError) as e:
        result["error"] = str(e)
        result["crawl_allowed"] = True  # Fail open: assume allowed if can't check
        result["note"] = f"Could not fetch robots.txt: {str(e)[:100]}"

    return result


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
    except (httpx.HTTPError, httpx.RequestError):
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
        except (httpx.HTTPError, httpx.RequestError):
            continue

    # Run all checks
    jurisdiction = detect_jurisdiction(url, html)
    tos_result: dict[str, Any] = (
        classify_tos(tos_text)  # type: ignore[arg-type]  # classify_tos returns dict[str, Any]
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

    # LLM fallback for ToS classification when the regex pass is low-confidence
    # or no ToS page was found. The LLM gets the ToS text (or page HTML if no
    # ToS) and returns a richer risk classification. Best-effort: if the
    # LLM call fails or no provider is configured, we keep the regex result.
    if tos_result.get("confidence") == "low" or not tos_text:
        try:
            from llm_features import llm_compliance_analyze

            llm_input = tos_text if tos_text else html[:8000]
            llm_result = await llm_compliance_analyze(llm_input, url=url)
            if llm_result and llm_result.get("risk_level"):
                tos_result = {
                    **tos_result,
                    "classification": llm_result.get("risk_level", tos_result["classification"]),
                    "confidence": llm_result.get("confidence", "medium"),
                    "matches": tos_result.get("matches", {}),
                    "note": (tos_result.get("note", "") + " | LLM-enhanced").strip(" |"),
                    "llm_enhanced": True,
                    "llm_risk_summary": llm_result.get("risk_summary", ""),
                    "llm_recommendation": llm_result.get("recommendation", ""),
                    "llm_key_restrictions": llm_result.get("key_restrictions", []),
                    "llm_provider": llm_result.get("llm_provider", ""),
                    "llm_cost_usd": llm_result.get("llm_cost_usd", 0.0),
                }
        except Exception as e:  # noqa: BLE001 - LLM fallback must catch all errors
            logger.debug("llm_compliance_fallback_failed", extra={"url": url, "error": str(e)[:80]})

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
            "llm_enhanced": tos_result.get("llm_enhanced", False),
            "llm_provider": tos_result.get("llm_provider", ""),
            "llm_cost_usd": tos_result.get("llm_cost_usd", 0.0),
            "llm_risk_summary": tos_result.get("llm_risk_summary", ""),
            "llm_recommendation": tos_result.get("llm_recommendation", ""),
            "llm_key_restrictions": tos_result.get("llm_key_restrictions", []),
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


__all__ = [
    "TOS_INDICATORS",
    "check_robots_txt",
    "classify_tos",
    "run_compliance_check",
]
