# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""JSON-Schema-subset validation for the MCP ``outputSchema`` contract.

Pry's contract is stricter than JSON Schema. JSON Schema tolerates absent
optional properties, which is how a tool could advertise ``data.content`` for
months while never emitting it. ``validate_payload`` therefore checks both
directions: declared types match, and everything declared is really emitted.
"""

from __future__ import annotations

from typing import Any

CHECKS: dict[str, Any] = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
    "integer": int,
    "number": (int, float),
}

#: Fields emitted only on the failure path, covered by their own test.
DIAGNOSTIC = {"error"}


def _type_ok(value: Any, declared: Any) -> bool:
    """True when ``value`` matches a JSON-Schema ``type`` (str or list)."""
    for name in declared if isinstance(declared, list) else [declared]:
        expected = CHECKS.get(name)
        if expected is None or (name in ("integer", "number") and isinstance(value, bool)):
            continue
        if isinstance(value, expected):
            return True
    return False


def _validate(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    """Check declared types, required properties and array item shapes."""
    if "type" in schema and not _type_ok(value, schema["type"]):
        raise AssertionError(f"{path}: expected {schema['type']}, got {type(value).__name__}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            assert key in value, f"{path}: missing required property {key!r}"
        for key, sub in (schema.get("properties") or {}).items():
            if key in value:
                _validate(value[key], sub, f"{path}.{key}")
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            _validate(item, schema["items"], f"{path}[{index}]")


def _declared(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    """Every declared property must appear in the payload actually emitted."""
    if not isinstance(value, dict):
        return
    for key, sub in (schema.get("properties") or {}).items():
        if key in DIAGNOSTIC:
            continue
        assert key in value, f"{path}: schema declares {key!r} but never emits it"
        if not isinstance(sub, dict):
            continue
        if "properties" in sub:
            _declared(value[key], sub, f"{path}.{key}")
        if isinstance(value[key], list) and "items" in sub:
            for index, item in enumerate(value[key]):
                _declared(item, sub["items"], f"{path}.{key}[{index}]")


def validate_payload(payload: Any, schema: dict[str, Any]) -> None:
    """Validate a payload against a tool's declared ``outputSchema``."""
    _validate(payload, schema)
    if not isinstance(payload, dict) or payload.get("success") is not False:
        _declared(payload, schema)
