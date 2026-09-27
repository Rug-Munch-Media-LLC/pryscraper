#!/usr/bin/env python3
"""Zone and handler classification for the antipattern triage report.

One question only: given a path or an ``except`` handler, which bucket does it
belong in? ``tests/`` vs ``src/`` vs other, and for a handler, does the failure
reach the caller as an explicit value or fall through silently.

The failure test is a triage heuristic grounded in the shapes this repo actually
returns from handlers (a failure constant, a non-empty error string, a dict /
tuple result, a result constructor, either branch of a conditional) — not a
proof. A count here is a starting point for a human, never a verdict.
"""

from __future__ import annotations

import ast

ZONES = ("tests", "src", "other")

EXPLICIT = "explicit-failure-return"
PASSTHROUGH = "value-passthrough"
SILENT = "silent-fallthrough"
CLASSES = (EXPLICIT, PASSTHROUGH, SILENT)

# A result constructor (VerifyResult, _failure, SettleOutcome) is a structured
# result in object form, the way a dict or tuple is in value form.
_CTOR_KEYS = ("result", "verdict", "error", "failure", "verifier", "outcome", "settle")
_FAILURE_CONSTANTS = (None, False, 0, "", ())


def zone_of(parts: tuple[str, ...]) -> str:
    """Classify a path tuple into tests/, src/ or other (scripts/, alembic/, ...)."""
    if "tests" in parts:
        return "tests"
    if "src" in parts:
        return "src"
    return "other"


def is_failure_value(node: ast.expr) -> bool:
    """True when a returned expression encodes a failed outcome for its caller.

    A bare name is a value-passthrough, not a failure: it could be anything, and
    counting it as a handled failure would let a swallowed exception hide behind
    an unrecognised local.
    """
    if isinstance(node, ast.Constant):
        if node.value in _FAILURE_CONSTANTS:
            return True
        return isinstance(node.value, str) and bool(node.value)
    if isinstance(node, ast.Dict):
        return bool(node.values)
    if isinstance(node, (ast.Tuple, ast.List)):
        return bool(node.elts)
    if isinstance(node, ast.Call):
        return any(key in ast.unparse(node.func).lower() for key in _CTOR_KEYS)
    if isinstance(node, ast.IfExp):
        return is_failure_value(node.body) or is_failure_value(node.orelse)
    return False


def classify_handler(handler: ast.ExceptHandler) -> str:
    """Split one except handler into explicit-failure / passthrough / silent."""
    values = [r.value for r in ast.walk(handler) if isinstance(r, ast.Return)]
    if any(v is not None and is_failure_value(v) for v in values):
        return EXPLICIT
    if any(v is not None for v in values):
        return PASSTHROUGH
    return SILENT
