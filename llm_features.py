"""Pry — Real LLM-powered features. Replaces regex stubs with actual LLM calls.
Used by compliance, SEO, entity reconciliation, PII redaction, and other AI features."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import json
import logging
from typing import Any

from llm_providers.registry import get_registry

logger = logging.getLogger(__name__)


def _strip_fence(text: str) -> str:
    """Strip markdown code fences that LLMs commonly wrap JSON in."""
    t = text.strip()
    if t.startswith("```json"):
        t = t[len("```json"):]
    elif t.startswith("```"):
        t = t[len("```"):]
    if t.endswith("```"):
        t = t[: -len("```")]
    return t.strip()


async def llm_compliance_analyze(text: str, url: str = "") -> dict[str, Any]:
    """Use LLM to actually analyze Terms of Service for compliance risk."""
    if not text:
        return {"risk_level": "unknown", "reason": "No ToS text provided"}
    prompt = f"""Analyze the following Terms of Service for legal compliance risks when scraping the associated website.

URL: {url}

Terms of Service (truncated to 4000 chars):
{text[:4000]}

Return JSON with these fields:
- risk_level: "green" (no restrictions), "yellow" (some restrictions), "red" (prohibits scraping)
- confidence: "high" / "medium" / "low"
- key_restrictions: list of strings describing scraping-related restrictions
- risk_summary: 1-2 sentence summary
- recommendation: what to do before scraping

Respond ONLY with valid JSON, no markdown formatting."""
    try:
        reg = get_registry()
        resp = await reg.complete(
            prompt,
            system=(
                "You are a legal compliance analyst specializing in web scraping. "
                "Be concise and accurate."
            ),
            max_tokens=800,
            temperature=0.3,
        )
        result = json.loads(_strip_fence(resp.text))
        result["llm_provider"] = resp.provider
        result["llm_cost_usd"] = round(resp.cost_usd, 6)
        return result
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("llm_compliance_failed", extra={"error": str(e)[:80]})
        return {"risk_level": "unknown", "error": str(e)[:200]}


async def llm_seo_analyze(
    url: str, content: str, target_keywords: list[str] | None = None
) -> dict[str, Any]:
    """Use LLM to analyze SEO quality of a page and identify optimization opportunities."""
    if not content:
        return {"score": 0, "recommendations": []}
    keywords = ", ".join(target_keywords) if target_keywords else "general relevance"
    prompt = f"""Analyze the SEO quality of this page for target keywords: {keywords}

URL: {url}
Page content (truncated):
{content[:3000]}

Return JSON with:
- overall_score: 0-100
- title_quality: "good" / "fair" / "poor"
- content_depth: "comprehensive" / "adequate" / "shallow"
- keyword_presence: {{keyword: "well_optimized" / "under_optimized" / "missing"}}
- recommendations: list of 3-5 specific actionable improvements
- issues: list of SEO problems found

Respond ONLY with valid JSON."""
    try:
        reg = get_registry()
        resp = await reg.complete(prompt, max_tokens=1000, temperature=0.3)
        return json.loads(_strip_fence(resp.text))
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("llm_seo_failed", extra={"error": str(e)[:80]})
        return {"score": 0, "error": str(e)[:200]}


async def llm_entity_reconcile(records: list[dict], vertical: str = "product") -> dict[str, Any]:
    """Use LLM to semantically match and merge records from different sources."""
    if not records or len(records) < 2:
        return {"entities": records, "matches": []}
    sample = records[:50]
    prompt = f"""You are a data reconciliation expert. Given records from multiple sources for the same {vertical} vertical, identify which records refer to the same real-world entity.

Records (JSON):
{json.dumps(sample, indent=2, default=str)[:8000]}

Return JSON with:
- groups: list of groups, each with a "canonical_id" (string) and "record_indices" (list of integers referring to the input records)
- unmatched: list of record indices that don't match any other record
- reasoning: brief explanation of how you matched

Respond ONLY with valid JSON."""
    try:
        reg = get_registry()
        resp = await reg.complete(prompt, max_tokens=2000, temperature=0.2)
        return json.loads(_strip_fence(resp.text))
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("llm_reconcile_failed", extra={"error": str(e)[:80]})
        return {"entities": records, "matches": [], "error": str(e)[:200]}


async def llm_pii_detect(text: str) -> dict[str, Any]:
    """Use LLM to detect PII that regex might miss (context-aware)."""
    if not text or len(text) < 50:
        return {"pii_found": [], "redacted_text": text}
    prompt = f"""Find all personally identifiable information (PII) in this text that should be redacted for safe AI training data use.

Text:
{text[:4000]}

Return JSON with:
- pii_items: list of {{"text": "the PII", "type": "name/email/phone/ssn/address/other", "start": character_index, "end": character_index}}
- redacted_text: the original text with PII replaced by [REDACTED:TYPE]

Respond ONLY with valid JSON. Use character indices relative to the original text (truncated to 4000 chars)."""
    try:
        reg = get_registry()
        resp = await reg.complete(prompt, max_tokens=2000, temperature=0.1)
        return json.loads(_strip_fence(resp.text))
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("llm_pii_failed", extra={"error": str(e)[:80]})
        return {"pii_items": [], "redacted_text": text, "error": str(e)[:200]}


async def llm_anomaly_detect(
    historical_data: list[dict], current: dict, field: str = "price"
) -> dict[str, Any]:
    """Use LLM to detect anomalies that statistical methods miss (context-aware).
    E.g., Black Friday prices dropping 50% is expected, but a 50% drop on a random Tuesday is suspicious."""
    if not historical_data or not current:
        return {"anomaly": False, "reason": "Insufficient data"}
    prompt = f"""Analyze whether this change in '{field}' is a true anomaly or an expected pattern.

Historical data (last 10):
{json.dumps(historical_data[-10:], default=str)}

Current value:
{json.dumps(current, default=str)}

Consider:
- Day of week / seasonal patterns
- Promotional events (Black Friday, holidays)
- Market conditions
- Whether the change is in the expected direction

Return JSON with:
- is_anomaly: bool
- confidence: 0.0-1.0
- reasoning: 1-2 sentences
- context_factors: list of relevant context that explain the change

Respond ONLY with valid JSON."""
    try:
        reg = get_registry()
        resp = await reg.complete(prompt, max_tokens=500, temperature=0.3)
        return json.loads(_strip_fence(resp.text))
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("llm_anomaly_failed", extra={"error": str(e)[:80]})
        return {"is_anomaly": False, "reason": str(e)[:200]}
