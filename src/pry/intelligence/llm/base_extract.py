"""Pry — LLM JSON extraction: fence stripping, schema coercion, response parsing.

Split out of ``base.py`` (2026-09-06) — see ``base.py`` for the re-export facade.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pry.intelligence.llm.base_client import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)


def strip_fences(text: str) -> str:
    """Strip markdown code fences that LLMs commonly wrap JSON in."""
    t = text.strip()
    if t.startswith("```json"):
        t = t[len("```json") :]
    elif t.startswith("```"):
        t = t[len("```") :]
    if t.endswith("```"):
        t = t[: -len("```")]
    return t.strip()


# ── Schema coercion ──────────────────────────────────────────────


def _to_int(value: Any) -> Any:
    try:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        return int(float(value))
    except (TypeError, ValueError):
        return value


def _to_float(value: Any) -> Any:
    try:
        if isinstance(value, float):
            return value
        return float(value)
    except (TypeError, ValueError):
        return value


def _to_bool(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    if isinstance(value, (int, float)):
        return bool(value)
    return value


def _to_list(value: Any) -> Any:
    # Never guess-split strings — a wrong split is worse than leaving data intact.
    return value


_SCALAR_COERCERS: dict[str, Callable[[Any], Any]] = {
    "str": str,
    "int": _to_int,
    "float": _to_float,
    "bool": _to_bool,
    "list": _to_list,
    "dict": lambda v: v,
    "any": lambda v: v,
}


def coerce_to_schema(data: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Coerce parsed JSON to a schema, filling missing keys with None.

    Schema format (lightweight, no JSON-Schema dependency):
        {"risk_level": "green|yellow|red", "score": "int", "tags": {"type": "list"},
         "nested": {"sub": "float"}}

    Rules:
    - Scalar type strings ("str", "int", "float", "bool", "list", "dict", "any")
      coerce the value; uncoercible values are left as-is (never crash).
    - "a|b|c" is an enum — values not in the list are left as-is.
    - A nested dict spec is applied recursively.
    - ``{"type": "list", "items": {...}}`` coerces list members.
    - Missing keys are filled with ``None``; unknown keys are preserved.
    """
    for key, spec in schema.items():
        if key not in data:
            data[key] = None
            continue
        value = data[key]
        if isinstance(spec, dict):
            if spec.get("type") == "list":
                items = spec.get("items")
                if isinstance(value, list) and isinstance(items, dict):
                    data[key] = [
                        coerce_to_schema(item, items) if isinstance(item, dict) else item
                        for item in value
                    ]
                elif value is not None and not isinstance(value, list):
                    data[key] = _SCALAR_COERCERS.get("list", lambda v: v)(value)
            else:
                # Nested object schema
                if isinstance(value, dict):
                    data[key] = coerce_to_schema(dict(value), spec)
                elif value is not None:
                    data[key] = _SCALAR_COERCERS.get("dict", lambda v: v)(value)
            continue
        if not isinstance(spec, str):
            continue
        if "|" in spec:
            allowed = {part.strip() for part in spec.split("|")}
            if isinstance(value, str) and value.strip().lower() in {a.lower() for a in allowed}:
                data[key] = value.strip()
            # Non-matching enum values are preserved for callers to judge.
            continue
        coercer = _SCALAR_COERCERS.get(spec)
        if coercer is not None and value is not None:
            data[key] = coercer(value)
    return data


def parse_json_response(
    text: str,
    schema: dict[str, Any] | None = None,
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Parse an LLM response as JSON, strip fences, coerce to schema.

    Returns ``dict(fallback or {})`` on any parse failure or non-dict payload —
    the "safe fallback" contract so callers never crash on malformed output.
    """
    try:
        data = json.loads(strip_fences(text))
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        logger.warning("llm_json_parse_failed", extra={"error": str(e)[:120]})
        return dict(fallback or {})
    if not isinstance(data, dict):
        logger.warning("llm_json_not_object")
        return dict(fallback or {})
    if schema:
        data = coerce_to_schema(data, schema)
    return data


def attach_llm_metadata(
    data: dict[str, Any], response: "LLMResponse", provider: "LLMProvider"
) -> dict[str, Any]:
    """Attach provider/cost metadata to a parsed JSON result (setdefault, no overwrite)."""
    data.setdefault("llm_provider", response.provider or provider.name)
    data.setdefault(
        "llm_cost_usd",
        round(provider.estimate_cost(response.input_tokens, response.output_tokens), 6),
    )
    data.setdefault("llm_input_tokens", response.input_tokens)
    data.setdefault("llm_output_tokens", response.output_tokens)
    return data
