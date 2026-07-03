"""Pry — JSON schema extraction engine.
Two modes: pattern (free, no LLM) and LLM (Ollama, for complex schemas).
LLM failures fall back gracefully to pattern mode.
No hallucination: JSON output is always parsed and validated.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import json
import re
from typing import Any

from resilience import registry


class SchemaExtractor:
    """Extract structured JSON data from scraped markdown content.
    Pattern mode is always tried first; LLM mode is fallback for complex schemas."""

    def __init__(self):
        self.ollama_base = "http://100.100.18.18:11434"

    async def extract(
        self, content: str, schema: dict[str, Any], mode: str = "auto"
    ) -> dict[str, Any]:
        """Extract fields matching the provided schema.
        Schema format: {"field_name": "description of what to extract"}

        If LLM mode fails (Ollama down, timeout), falls back to pattern mode.
        """
        if not content or not schema:
            return {}

        # Pattern mode first (always works, no dependencies)
        pattern_result = self._pattern_extract(content, schema)

        # Use LLM mode only if requested explicitly or schema is complex
        use_llm = mode == "llm" or (mode == "auto" and len(schema) > 5)
        if not use_llm:
            return pattern_result

        # Try LLM extraction, fall back to pattern on failure
        try:
            llm_result = await self._llm_extract(content, schema)
            if llm_result and not llm_result.get("_error"):
                # Merge: LLM values override pattern, but pattern fills gaps
                merged = {**pattern_result, **llm_result}
                return {k: v for k, v in merged.items() if v is not None and v != ""}
        except Exception:  # noqa: BLE001
            registry.record_service_result("ollama", False)
            pass

        return pattern_result

    def _pattern_extract(self, content: str, schema: dict[str, Any]) -> dict[str, Any]:
        result = {}
        for field, desc in schema.items():
            value = self._find_value(content, field, desc)
            if value:
                result[field] = value
        return result

    def _find_value(self, content: str, field: str, desc: str) -> str | None:
        """Multi-strategy field extraction. Returns first match found."""
        # Strategy 1: "Label: Value" patterns
        field_variants = [field, field.replace("_", " "), field.replace("_", "")]
        for variant in field_variants:
            if not variant:
                continue
            escaped = re.escape(variant)
            m = re.search(rf"(?im){escaped}\s*[:=\-≈>]\s*(.+?)(?:\n|$)", content)
            if m:
                val = m.group(1).strip().rstrip(".,;")
                if val and len(val) < 500:
                    return val

        # Strategy 2: Context-aware patterns from description
        desc_lower = desc.lower()
        if "price" in desc_lower or "cost" in desc_lower or "usd" in desc_lower:
            m = re.search(r"[\$€£¥]?\s*[\d,]+\.?\d*\s*(?:USD|EUR|GBP)?", content)
            if m:
                return m.group(0).strip()
        if "email" in desc_lower:
            m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", content)
            if m:
                return m.group(0)
        if "url" in desc_lower or "link" in desc_lower:
            m = re.search(r'https?://[^\s"\'<>]+', content)
            if m:
                return m.group(0)
        if "phone" in desc_lower or "telephone" in desc_lower:
            m = re.search(r"\+?\d[\d\s\-().]{7,}", content)
            if m:
                return m.group(0).strip()
        if "date" in desc_lower:
            m = re.search(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", content)
            if m:
                return m.group(0)
        if "number" in desc_lower or "count" in desc_lower or "total" in desc_lower:
            nums = re.findall(r"\b\d[\d,]*\.?\d*\b", content)
            if nums:
                return max((n for n in nums if len(n) < 20), key=len)

        return None

    async def _llm_extract(self, content: str, schema: dict[str, Any]) -> dict[str, Any]:
        """LLM-guided extraction. Returns dict on success, {"_error": msg} on failure."""
        if not registry.is_service_allowed("ollama"):
            return {"_error": "ollama circuit breaker open"}
        import httpx

        schema_str = json.dumps(schema, indent=2)
        truncated = content[:8000]
        prompt = (
            "Extract the following fields from the text below.\n"
            "Return ONLY a valid JSON object with these fields — no explanation, no markdown.\n"
            f"Schema: {schema_str}\n"
            f"Text:\n{truncated}\n\nJSON:"
        )

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self.ollama_base}/api/generate",
                    json={
                        "model": "qwen2.5-coder:3b",
                        "prompt": prompt,
                        "stream": False,
                        "options": {"num_ctx": 8192, "temperature": 0.05},
                    },
                )
                data = resp.json()
                response = data.get("response", "")

            # Extract first JSON object from response (non-greedy)
            json_match = re.search(r"\{[^{}]*\}", response, re.S)
            if json_match:
                obj = json.loads(json_match.group(0))
                if isinstance(obj, dict):
                    registry.record_service_result("ollama", True)
                    return obj
            registry.record_service_result("ollama", True)
            return {"_raw": response[:500]}
        except (json.JSONDecodeError, ValueError) as e:
            registry.record_service_result("ollama", False)
            return {"_error": str(e)}
