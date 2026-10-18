"""Schema normalization, confidence scoring and example-based inference.

Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
Licensed under MIT. See LICENSE.
"""

from __future__ import annotations

from typing import Any


def normalize_schema(schema: dict[str, Any] | None) -> dict[str, str]:
    """Normalize a user schema to ``{field_name: description}``.

    Accepts either the flat form ``{"price": "product price"}`` or the
    structured form ``{"fields": [{"name": "price", "description": ...}]}``.
    """
    if not isinstance(schema, dict):
        return {}
    fields = schema.get("fields")
    if isinstance(fields, list):
        out: dict[str, str] = {}
        for f in fields:
            if isinstance(f, dict) and f.get("name"):
                out[str(f["name"])] = str(f.get("description") or f["name"])
        return out
    return {str(k): str(v) for k, v in schema.items() if k != "fields"}


def confidence(data: dict[str, Any], schema: dict[str, str], method: str) -> float:
    """Simple confidence score: fraction of schema fields filled, weighted by source."""
    if not schema:
        return 0.0
    filled = sum(1 for f in schema if data.get(f) not in (None, "", [], {}))
    base = filled / len(schema)
    if method == "pattern":
        return round(min(base, 1.0), 2)
    if method == "ai":
        return round(min(base * 0.85, 1.0), 2)  # LLM output slightly less trusted
    return round(min(base, 1.0), 2)  # hybrid: pattern-anchored


def _field_type(val: Any) -> str:
    if isinstance(val, bool):
        return "boolean"
    if isinstance(val, (int, float)):
        return "number"
    if isinstance(val, list):
        return "array"
    if isinstance(val, dict):
        return "object"
    return "string"


def infer_schema_from_example(example: dict) -> dict:
    """Generate a JSON schema from an example data dict.

    Given ``{"product_name": "Widget", "price": 9.99}``, returns a schema
    describing the expected output format — useful for users who don't want
    to write schemas manually. Never raises.
    """
    if not isinstance(example, dict):
        return {}
    fields: list[dict[str, str]] = [
        {
            "name": str(key),
            "type": _field_type(val),
            "description": f"the {str(key).replace('_', ' ')}",
        }
        for key, val in example.items()
    ]
    return {
        "type": "object",
        "properties": {f["name"]: {"type": f["type"]} for f in fields},
        "fields": fields,
    }


__all__ = ["confidence", "infer_schema_from_example", "normalize_schema"]
