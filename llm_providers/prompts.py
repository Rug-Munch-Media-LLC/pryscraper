"""Pry — Versionable LLM prompt registry.

Inline prompts used by :mod:`llm_features` live here so they can be versioned,
tested, and tuned without touching feature code. Each entry carries the user
template, optional system prompt, a lightweight output schema (see
``llm_providers.base.coerce_to_schema``), and default sampling params.

Templates use ``str.format`` — literal braces must be doubled (``{{`` / ``}}``).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
from __future__ import annotations

from typing import Any

PROMPTS: dict[str, dict[str, Any]] = {
    "compliance_analyze": {
        "description": "Analyze Terms of Service for scraping compliance risk.",
        "system": (
            "You are a legal compliance analyst specializing in web scraping. "
            "Be concise and accurate."
        ),
        "user": """Analyze the following Terms of Service for legal compliance risks when scraping the associated website.

URL: {url}

Terms of Service (truncated to 4000 chars):
{text}

Return JSON with these fields:
- risk_level: "green" (no restrictions), "yellow" (some restrictions), "red" (prohibits scraping)
- confidence: "high" / "medium" / "low"
- key_restrictions: list of strings describing scraping-related restrictions
- risk_summary: 1-2 sentence summary
- recommendation: what to do before scraping

Respond ONLY with valid JSON, no markdown formatting.""",
        "schema": {
            "risk_level": "green|yellow|red|unknown",
            "confidence": "high|medium|low|unknown",
            "key_restrictions": {"type": "list"},
            "risk_summary": "str",
            "recommendation": "str",
        },
        "max_tokens": 800,
        "temperature": 0.3,
    },
    "seo_analyze": {
        "description": "Analyze on-page SEO quality for target keywords.",
        "system": "You are an SEO analyst. Be specific and actionable.",
        "user": """Analyze the SEO quality of this page for target keywords: {keywords}

URL: {url}
Page content (truncated):
{content}

Return JSON with:
- overall_score: 0-100
- title_quality: "good" / "fair" / "poor"
- content_depth: "comprehensive" / "adequate" / "shallow"
- keyword_presence: {{keyword: "well_optimized" / "under_optimized" / "missing"}}
- recommendations: list of 3-5 specific actionable improvements
- issues: list of SEO problems found

Respond ONLY with valid JSON.""",
        "schema": {
            "overall_score": "int",
            "title_quality": "good|fair|poor",
            "content_depth": "comprehensive|adequate|shallow",
            "keyword_presence": {},
            "recommendations": {"type": "list"},
            "issues": {"type": "list"},
        },
        "max_tokens": 1000,
        "temperature": 0.3,
    },
    "entity_reconcile": {
        "description": "Match records from different sources to the same real-world entity.",
        "system": "You are a data reconciliation expert.",
        "user": """You are a data reconciliation expert. Given records from multiple sources for the same {vertical} vertical, identify which records refer to the same real-world entity.

Records (JSON):
{sample_json}

Return JSON with:
- groups: list of groups, each with a "canonical_id" (string) and "record_indices" (list of integers referring to the input records)
- unmatched: list of record indices that don't match any other record
- reasoning: brief explanation of how you matched

Respond ONLY with valid JSON.""",
        "schema": {
            "groups": {"type": "list"},
            "unmatched": {"type": "list"},
            "reasoning": "str",
        },
        "max_tokens": 2000,
        "temperature": 0.2,
    },
    "pii_detect": {
        "description": "Context-aware PII detection for safe training-data use.",
        "system": "You are a privacy engineer specializing in PII redaction.",
        "user": """Find all personally identifiable information (PII) in this text that should be redacted for safe AI training data use.

Text:
{text}

Return JSON with:
- pii_items: list of {{"text": "the PII", "type": "name/email/phone/ssn/address/other", "start": character_index, "end": character_index}}
- redacted_text: the original text with PII replaced by [REDACTED:TYPE]

Respond ONLY with valid JSON. Use character indices relative to the original text (truncated to 4000 chars).""",
        "schema": {
            "pii_items": {"type": "list"},
            "redacted_text": "str",
        },
        "max_tokens": 2000,
        "temperature": 0.1,
    },
    "anomaly_detect": {
        "description": "Context-aware anomaly detection beyond statistical methods.",
        "system": "You are a data analyst specializing in anomaly detection.",
        "user": """Analyze whether this change in '{field}' is a true anomaly or an expected pattern.

Historical data (last 10):
{historical}

Current value:
{current}

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

Respond ONLY with valid JSON.""",
        "schema": {
            "is_anomaly": "bool",
            "confidence": "float",
            "reasoning": "str",
            "context_factors": {"type": "list"},
        },
        "max_tokens": 500,
        "temperature": 0.3,
    },
}


def render_prompt(name: str, **kwargs: Any) -> str:
    """Render a PROMPTS user template with keyword args.

    Raises:
        KeyError: if ``name`` is not a known prompt.
    """
    spec = PROMPTS[name]
    return spec["user"].format(**kwargs)


def get_prompt(name: str) -> dict[str, Any]:
    """Return a shallow copy of a prompt spec (versionable/testable)."""
    return dict(PROMPTS[name])
