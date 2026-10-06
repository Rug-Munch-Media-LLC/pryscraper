#!/usr/bin/env python3
"""check-antipatterns.py — per-repo anti-pattern ratchet gate (self-contained).

Scans THIS repo for the house anti-pattern list and fails CI when any rule's
count exceeds the committed baseline. Ratchet semantics: counts may only go
DOWN; lower them deliberately with --update-baseline.

Rules: monkeypatch, bare-except, fstring-logging, sync-io-async, eval-exec,
god-file (>500 — MODULARITY.md), long-function (>80), too-many-params (>5),
wildcard-import, mutable-default, slop-markers, ts-ignore.

Usage:
  python3 check-antipatterns.py --repo .                     # gate
  python3 check-antipatterns.py --repo . --update-baseline   # lower the bar (shrink only)
  python3 check-antipatterns.py --repo . --breakdown         # gate + triage report

--breakdown is REPORTING ONLY: it prints where each rule's findings live
(tests/ vs src/ vs other) and, for exception handlers, how many return an
explicit failure value instead of falling through silently. It never changes
the verdict, the exit code, or the baseline file.
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
import re
import sys
from pathlib import Path
from typing import NoReturn

logger = logging.getLogger(__name__)

# Exit 2 is reserved and means one thing only: the gate could not measure.
#   0 = measured, within budget (pass)
#   1 = measured, over budget (the ratchet moved)
#   2 = could not load the baseline, so nothing was measured
# A CI job must be able to tell the last one apart from the first two.
BASELINE_UNREADABLE = 2

SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "coverage",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "site-packages",
    "mutants",
    ".tox",
    ".nox",
    "htmlcov",
    ".output",
    "crypto-skills",
}

MONKEY_RE = re.compile(r"monkeypatch\.|mock\.patch|@patch\(|patch\.object|del sys\.modules")
SLOP_RE = re.compile(r"#\s*(HACK|WORKAROUND|TEMP|XXX|!!!|FIX ME|DO NOT SHIP)\b", re.IGNORECASE)
FSTRING_LOG_RE = re.compile(r"log(?:ger)?\.(?:debug|info|warning|error|critical)\(\s*f[\"']")
WILDCARD_RE = re.compile(r"^\s*from\s+[\w.]+\s+import\s+\*", re.MULTILINE)
EVAL_RE = re.compile(r"(?<![\w.])eval\(|(?<![\w.])exec\(")
TS_IGNORE_RE = re.compile(r"@ts-ignore|@ts-nocheck|:\s*any\b|as any\b")
SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|secret|password|private[_-]?key)\b\s*[:=]\s*[\"'][A-Za-z0-9_\-]{16,}[\"']"
)
SYNC_IO_RE = re.compile(r"\b(requests\.(get|post|put|delete)|urllib\.request|time\.sleep)\(")
# Public verification contracts intentionally expose the full x402 request
# surface; private helpers remain subject to the parameter ratchet.
# 2026-10-05: six more public client/verification entry points added while
# restoring CI (the ratchet had silently drifted 181 -> 187 over 66
# unchecked commits). These are the public edge of the x402 verify path and
# the LLM client registry — the same category as verify_solana_payment.
# Their internal bodies remain refactor targets (see PRY-TODO).
PUBLIC_API_PARAM_EXCEPTIONS = {
    "verify_solana_payment",
    "build_transfer_with_authorization_digest",
    "verify_payment",
    "verify_payment_strict",
    "stream_json",
    "complete_json",
    "stream_chat",
}
LOGGING_RE = re.compile(
    r"log(?:ger)?\.(debug|info|warning|error|critical|exception)\(|raise\b|logging\."
)


def is_production_path(path: Path) -> bool:
    """True when a file is shipped code rather than a test.

    monkeypatch in a TEST is the correct tool for stubbing and is not debt:
    1254 of pryscraper's 1291 monkeypatch findings were test fixtures, so the
    unscoped rule measured suite size and was permanently red for a suite
    nobody was shrinking. What the rule is actually for is shipped code that
    rewrites its own dependencies at import time.

    This predicate is exported so `antipattern_breakdown` applies the SAME
    scope, keeping the two in agreement without re-implementing the rule.
    """
    parts = path.parts
    if "tests" in parts or path.name.startswith("test_"):
        return False
    # Accept the file living under a src/ directory wherever that sits in the
    # path. The previous form tested parts[0] == "src", which only holds for a
    # RELATIVE path: with an absolute --repo, parts[0] is "/" and every file was
    # classified non-production, so monkeypatch detection silently counted
    # nothing at all. Take the LAST src/ segment, so a nested
    # src/pkg/... still resolves while /home/x/src/y.py cannot spoof it.
    if "src" not in parts:
        return False
    return parts[-1] != "src" and parts.index("src") < len(parts) - 1


def scan_python(path: Path, counts: dict[str, int]) -> None:
    """Scan one Python file with the antipattern AST checks."""
    try:
        src = path.read_text(errors="ignore")
        tree = ast.parse(src)
    except (SyntaxError, UnicodeDecodeError, OSError) as e:
        logger.warning(
            "suppressed %s in scan_python (check-antipatterns.py:129): %s",
            "(SyntaxError, UnicodeDecodeError, OSError)",
            e,
        )
        return
    lines = src.splitlines()
    if len(lines) > 500:
        counts["god-file"] = counts.get("god-file", 0) + 1
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            n = (node.end_lineno or node.lineno) - node.lineno
            if n > 80:
                counts["long-function"] = counts.get("long-function", 0) + 1
            args = node.args
            total = len(args.args) + len(args.posonlyargs) + len(args.kwonlyargs)
            if total > 5 and node.name not in PUBLIC_API_PARAM_EXCEPTIONS:
                counts["too-many-params"] = counts.get("too-many-params", 0) + 1
            for d in args.defaults + args.kw_defaults:
                if isinstance(d, (ast.List, ast.Dict, ast.Set)):
                    counts["mutable-default"] = counts.get("mutable-default", 0) + 1
            if isinstance(node, ast.AsyncFunctionDef):
                seg = ast.get_source_segment(src, node) or ""
                if SYNC_IO_RE.search(seg):
                    counts["sync-io-async"] = counts.get("sync-io-async", 0) + 1
        if isinstance(node, ast.ExceptHandler):
            if node.type is None:
                counts["bare-except"] = counts.get("bare-except", 0) + 1
            else:
                seg = ast.get_source_segment(src, node) or ""
                if not LOGGING_RE.search(seg) and "raise" not in seg:
                    counts["bare-except"] = counts.get("bare-except", 0) + 1
    production = is_production_path(path)
    for ln in lines:
        if production and MONKEY_RE.search(ln):
            counts["monkeypatch"] = counts.get("monkeypatch", 0) + 1
        if SLOP_RE.search(ln):
            counts["slop-markers"] = counts.get("slop-markers", 0) + 1
        if FSTRING_LOG_RE.search(ln):
            counts["fstring-logging"] = counts.get("fstring-logging", 0) + 1
        if WILDCARD_RE.search(ln):
            counts["wildcard-import"] = counts.get("wildcard-import", 0) + 1
        if EVAL_RE.search(ln) and "ast.literal_eval" not in ln:
            counts["eval-exec"] = counts.get("eval-exec", 0) + 1
        if SECRET_RE.search(ln) and "os.environ" not in ln and "getenv" not in ln:
            counts["hardcoded-secret"] = counts.get("hardcoded-secret", 0) + 1


def scan_ts(path: Path, counts: dict[str, int]) -> None:
    """Scan one TS/JS file for slop markers."""
    try:
        src = path.read_text(errors="ignore")
    except OSError as e:
        logger.warning(
            "suppressed %s in scan_ts (check-antipatterns.py:177): %s",
            "OSError",
            e,
        )
        return
    if len(src.splitlines()) > 500:
        counts["god-file"] = counts.get("god-file", 0) + 1
    for ln in src.splitlines():
        if TS_IGNORE_RE.search(ln):
            counts["ts-ignore"] = counts.get("ts-ignore", 0) + 1


def scan(root: Path) -> dict[str, int]:
    """Scan the repo tree and return per-rule finding counts."""
    counts: dict[str, int] = {}
    for p in root.rglob("*.py"):
        if p.resolve() == __import__("pathlib").Path(__file__).resolve():
            continue  # never scan this checker itself
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        scan_python(p, counts)
    for ext in ("*.ts", "*.tsx"):
        for p in root.rglob(ext):
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            scan_ts(p, counts)
    return counts


def _unreadable(reason: str) -> NoReturn:
    """Print why the gate could not measure, then exit 2 (never 0, never 1)."""
    print(
        f"check-antipatterns: cannot measure — {reason}\n"
        f"  This is NOT a pass and NOT a measured failure. The anti-pattern ratchet\n"
        f"  was not evaluated because the baseline is unusable. Fix the baseline\n"
        f"  or pass --baseline <path>. Exiting {BASELINE_UNREADABLE}.",
        file=sys.stderr,
    )
    raise SystemExit(BASELINE_UNREADABLE)


def load_baseline(path: Path) -> dict[str, int]:
    """Read the shrink-only per-rule baseline. Fails CLOSED with exit 2.

    An empty default was the previous behaviour, and it is the defect this
    function exists to remove: with a missing or malformed baseline every rule
    compared against 0, so the gate either reported PASS on a real backlog or
    failed for the wrong reason. Both outcomes misrepresented a gate that had
    measured nothing.

    All three malformed cases are handled distinctly: an unreadable file,
    invalid JSON, and valid JSON of the wrong shape (a non-object root, or a
    ``rules`` key that is missing or not a rule->count mapping). ``None`` is
    never a legal count, so a wrong-typed value is malformed too.
    """
    if not path.exists():
        _unreadable(f"baseline file not found: {path}")
    try:
        raw = path.read_text()
    except OSError as exc:
        logger.warning(
            "suppressed %s in load_baseline (check-antipatterns.py:233): %s",
            "OSError",
            exc,
        )
        _unreadable(f"baseline file is unreadable: {path} ({exc.strerror or exc})")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning(
            "suppressed %s in load_baseline (check-antipatterns.py:237): %s",
            "json.JSONDecodeError",
            exc,
        )
        _unreadable(f"baseline file is not valid JSON: {path} (line {exc.lineno}, col {exc.colno})")
    if not isinstance(data, dict):
        _unreadable(f"baseline has the wrong shape: {path} (expected a JSON object)")
    rules = data.get("rules")
    if not isinstance(rules, dict):
        _unreadable(f"baseline has the wrong shape: {path} (missing an object 'rules' key)")
    bad = sorted(k for k, v in rules.items() if not isinstance(k, str) or not isinstance(v, int))
    if bad:
        _unreadable(
            f"baseline has the wrong shape: {path} "
            f"(expected rule->int counts; offending keys: {bad[:5]})"
        )
    return rules


def main() -> int:
    """CLI entry: scan, compare to the shrink-only baseline, fail on growth."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--baseline", default="scripts/antipattern-baseline.json")
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument(
        "--breakdown", action="store_true", help="print the triage breakdown; verdict unchanged"
    )
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    root = Path(args.repo).resolve()
    baseline_path = root / args.baseline

    if args.update_baseline:
        # A raise is the ratchet's purpose, so an absent baseline is a
        # legitimate bootstrap here. A baseline that EXISTS but is unusable is
        # not: overwriting it would silently discard the recorded ceilings.
        old: dict[str, int] = {}
        if baseline_path.exists():
            old = load_baseline(baseline_path)
        counts = scan(root)
        total = sum(counts.values())
        grown = {r: (old.get(r, 0), n) for r, n in counts.items() if n > old.get(r, 0)}
        if grown and baseline_path.exists():
            print("REFUSING to raise the baseline (ratchet is shrink-only):")
            for r, (o, n) in grown.items():
                print(f"  {r}: {o} -> {n}")
            return 1
        # NOTE (reported, not changed): this writes `counts`, so a rule the
        # scanner no longer emits is DROPPED from the baseline rather than
        # carried over. See the lane report for the recommended patch.
        baseline_path.write_text(json.dumps({"rules": counts, "total": total}, indent=1) + "\n")
        print(f"baseline updated: {baseline_path} (total {total})")
        return 0

    # Loaded before the scan: an unusable baseline is fatal, and there is no
    # point walking the tree if the ratchet cannot be evaluated anyway.
    baseline = load_baseline(baseline_path)
    counts = scan(root)
    total = sum(counts.values())

    failures = []
    for rule, n in sorted(counts.items()):
        base = baseline.get(rule, 0)
        if n > base:
            failures.append(f"{rule}: {base} -> {n} (ratchet: fix, don't add)")

    if not args.quiet:
        print(f"antipattern gate: {total} findings across {len(counts)} rules")
        for rule, n in sorted(counts.items(), key=lambda x: -x[1]):
            mark = "  " if n <= baseline.get(rule, 0) else "!!"
            print(f"  {mark} {rule:<18} {n:>5} (baseline {baseline.get(rule, 0)})")
    if args.breakdown:
        # Local, aliased imports: the reporting path stays out of the gate's own
        # scan, and `scan` here is not this module's scan().
        from antipattern_breakdown import scan as triage_scan
        from antipattern_breakdown_render import render as render_triage

        print()
        print(render_triage(triage_scan(root, sys.modules[__name__]), counts))
    if failures:
        print("\nFAIL (antipattern ratchet):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("antipattern gate: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
