"""Pry — Real LLM-powered features. Replaces regex stubs with actual LLM calls.
Used by compliance, SEO, entity reconciliation, PII redaction, and other AI features.

All prompts live in :mod:`llm_providers.prompts` (PROMPTS registry) and every
LLM call goes through :meth:`llm_providers.registry.LLMRegistry.complete_json`
for schema-validated JSON output with provider fallback + retry + cost tracking.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import json
import logging
from typing import Any

from pry.intelligence.llm.prompts import PROMPTS, render_prompt
from pry.intelligence.llm.registry import get_registry

logger = logging.getLogger(__name__)


async def _llm_json_call(prompt_name: str, prompt: str, fallback: dict[str, Any]) -> dict[str, Any]:
    """Run a PROMPTS-registry prompt through the registry's JSON completion path.

    Always returns a dict — feature fallback on total failure, and never raises
    to callers (matches the pre-existing degrade-gracefully contract).
    """
    spec = PROMPTS[prompt_name]
    reg = get_registry()
    try:
        return await reg.complete_json(
            prompt,
            schema=spec.get("schema"),
            system=spec.get("system", ""),
            max_tokens=spec.get("max_tokens", 1024),
            temperature=spec.get("temperature", 0.3),
            fallback=fallback,
        )
    except Exception as e:  # noqa: BLE001 - LLM features must never crash callers
        logger.warning("llm_json_call_failed", extra={"prompt": prompt_name, "error": str(e)[:100]})
        return dict(fallback)


async def llm_compliance_analyze(text: str, url: str = "") -> dict[str, Any]:
    """Use LLM to actually analyze Terms of Service for compliance risk."""
    if not text:
        return {"risk_level": "unknown", "reason": "No ToS text provided"}
    prompt = render_prompt("compliance_analyze", url=url, text=text[:4000])
    return await _llm_json_call(
        "compliance_analyze",
        prompt,
        {"risk_level": "unknown", "error": "LLM compliance analysis failed"},
    )


async def llm_seo_analyze(
    url: str, content: str, target_keywords: list[str] | None = None
) -> dict[str, Any]:
    """Use LLM to analyze SEO quality of a page and identify optimization opportunities."""
    if not content:
        return {"score": 0, "recommendations": []}
    keywords = ", ".join(target_keywords) if target_keywords else "general relevance"
    prompt = render_prompt("seo_analyze", keywords=keywords, url=url, content=content[:3000])
    return await _llm_json_call(
        "seo_analyze", prompt, {"score": 0, "error": "LLM SEO analysis failed"}
    )


async def llm_entity_reconcile(records: list[dict], vertical: str = "product") -> dict[str, Any]:
    """Use LLM to semantically match and merge records from different sources."""
    if not records or len(records) < 2:
        return {"entities": records, "matches": []}
    sample = records[:50]
    sample_json = json.dumps(sample, indent=2, default=str)[:8000]
    prompt = render_prompt("entity_reconcile", vertical=vertical, sample_json=sample_json)
    return await _llm_json_call(
        "entity_reconcile",
        prompt,
        {"entities": records, "matches": [], "error": "LLM entity reconciliation failed"},
    )


async def llm_pii_detect(text: str) -> dict[str, Any]:
    """Use LLM to detect PII that regex might miss (context-aware)."""
    if not text or len(text) < 50:
        return {"pii_found": [], "redacted_text": text}
    prompt = render_prompt("pii_detect", text=text[:4000])
    return await _llm_json_call(
        "pii_detect",
        prompt,
        {"pii_items": [], "redacted_text": text, "error": "LLM PII detection failed"},
    )


async def llm_anomaly_detect(
    historical_data: list[dict], current: dict, field: str = "price"
) -> dict[str, Any]:
    """Use LLM to detect anomalies that statistical methods miss (context-aware).
    E.g., Black Friday prices dropping 50% is expected, but a 50% drop on a random Tuesday is suspicious."""
    if not historical_data or not current:
        return {"anomaly": False, "reason": "Insufficient data"}
    prompt = render_prompt(
        "anomaly_detect",
        field=field,
        historical=json.dumps(historical_data[-10:], default=str),
        current=json.dumps(current, default=str),
    )
    return await _llm_json_call(
        "anomaly_detect",
        prompt,
        {"is_anomaly": False, "reason": "LLM anomaly detection failed"},
    )
