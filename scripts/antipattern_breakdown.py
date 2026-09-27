#!/usr/bin/env python3
"""Reporting-only triage breakdown for the antipattern ratchet gate.

Splits every rule's findings by zone (``tests/`` vs ``src/`` vs other) and, for
exception handlers, separates an EXPLICIT FAILURE RETURN (the handler hands back
a verdict or error value, so the failure reaches the caller) from a SILENT
FALLTHROUGH (``pass``, a bare ``return``, or no return at all).

This module NEVER decides the verdict, the exit code, or the baseline file. It
reads the gate's own compiled patterns and exemptions, so per-rule totals
reconcile with the gate exactly (the report prints the reconciliation). The
handler classes are a triage heuristic, not a proof: a finding in ``tests/`` may
still be a real smell, and a mis-scoped rule is a gate bug, not a fixable file.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

from antipattern_handlers import CLASSES, ZONES, classify_handler, zone_of

_log = logging.getLogger(__name__)

# rule -> attribute holding the gate's own compiled pattern. One source of
# truth: the gate owns the patterns, this module only reads them.
LINE_RULES = {
    "monkeypatch": "MONKEY_RE",
    "slop-markers": "SLOP_RE",
    "fstring-logging": "FSTRING_LOG_RE",
    "wildcard-import": "WILDCARD_RE",
    "eval-exec": "EVAL_RE",
    "hardcoded-secret": "SECRET_RE",
}
TS_RULES = {"ts-ignore": "TS_IGNORE_RE"}
AST_RULES = ("bare-except", "long-function", "too-many-params", "mutable-default")
ALL_RULES = (*LINE_RULES, *TS_RULES, *AST_RULES, "god-file")


def _bucket() -> dict:
    """One rule's per-zone tally: a total plus the three handler classes."""
    return {zone: {"n": 0, **dict.fromkeys(CLASSES, 0)} for zone in ZONES}


def _bump(data: dict, rule: str, zone: str, cls: str | None = None) -> None:
    """Count one finding for a rule in a zone, optionally tagged with a class."""
    cell = data[rule][zone]
    cell["n"] += 1
    if cls:
        cell[cls] += 1


def _guard(rule: str, line: str) -> bool:
    """True when a matching line is exempt by the gate's own per-line guard."""
    if rule == "eval-exec":
        return "ast.literal_eval" in line
    if rule == "hardcoded-secret":
        return "os.environ" in line or "getenv" in line
    return False


def _read(path: Path) -> str:
    """Read a source file; empty when unreadable, mirroring the gate's skip."""
    try:
        return path.read_text(errors="ignore")
    except OSError:
        _log.debug("unreadable, skipped: %s", path)
        return ""


def _tree(src: str) -> ast.AST | None:
    """Parse source; None when it will not parse, mirroring the gate's skip."""
    try:
        return ast.parse(src)
    except (SyntaxError, ValueError):
        _log.debug("unparseable source, skipped")
        return None


def _count_lines(src: str, zone: str, data: dict, rules: dict) -> None:
    """Count every line-based rule for one file, honouring the gate's guards."""
    lines = src.splitlines()
    for line in lines:
        for rule, rx in rules.items():
            if rx.search(line) and not _guard(rule, line):
                _bump(data, rule, zone)
    if len(lines) > 500:
        _bump(data, "god-file", zone)


def _counts_as_bare_except(node: ast.ExceptHandler, src: str, gate) -> bool:
    """True when the gate would count this handler under the bare-except rule.

    Same two conditions the gate applies: an untyped `except:` always counts, a
    typed one counts only when it neither logs nor re-raises. Reimplemented here
    rather than imported so the handler-class tally stays independent of the
    gate; `test_breakdown_matches_gate_counts_exactly` is what pins them equal.
    """
    if node.type is None:
        return True
    seg = ast.get_source_segment(src, node) or ""
    return not gate.LOGGING_RE.search(seg) and "raise" not in seg


def _count_ast(zone: str, data: dict, gate, src: str, tree: ast.AST) -> None:
    """Count the node-shape rules, tagging exception handlers with a class."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if (node.end_lineno or node.lineno) - node.lineno > 80:
                _bump(data, "long-function", zone)
            args = node.args
            total = len(args.args) + len(args.posonlyargs) + len(args.kwonlyargs)
            if total > 5 and node.name not in gate.PUBLIC_API_PARAM_EXCEPTIONS:
                _bump(data, "too-many-params", zone)
            for d in args.defaults + args.kw_defaults:
                if isinstance(d, (ast.List, ast.Dict, ast.Set)):
                    _bump(data, "mutable-default", zone)
        elif isinstance(node, ast.ExceptHandler) and _counts_as_bare_except(node, src, gate):
            _bump(data, "bare-except", zone, classify_handler(node))


def scan(root: Path, gate) -> dict:
    """Return {rule: {zone: {n, class...}}} over exactly the files the gate scans.

    ``gate`` is the check-antipatterns module, passed in so the patterns, the
    skip list and the public-API exemptions have a single source of truth.
    """
    data = {rule: _bucket() for rule in ALL_RULES}
    line_rules = {r: getattr(gate, a) for r, a in LINE_RULES.items()}
    ts_rules = {r: getattr(gate, a) for r, a in TS_RULES.items()}
    self_path = Path(gate.__file__).resolve()
    for path in sorted(root.rglob("*.py")):
        if path.resolve() == self_path or any(x in gate.SKIP_DIRS for x in path.parts):
            continue
        zone, src = zone_of(path.parts), _read(path)
        _count_lines(src, zone, data, line_rules)
        tree = _tree(src)
        if tree is not None:
            _count_ast(zone, data, gate, src, tree)
    for ext in ("*.ts", "*.tsx"):
        for path in sorted(root.rglob(ext)):
            if any(x in gate.SKIP_DIRS for x in path.parts):
                continue
            _count_lines(_read(path), zone_of(path.parts), data, ts_rules)
    return data


def reconcile(data: dict, gate_counts: dict[str, int]) -> list[str]:
    """Return a list of rules whose zoned total disagrees with the gate's."""
    return [
        rule
        for rule, zones in sorted(data.items())
        if sum(z["n"] for z in zones.values()) != gate_counts.get(rule, 0)
    ]
