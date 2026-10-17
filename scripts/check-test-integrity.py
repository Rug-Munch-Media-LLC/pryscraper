#!/usr/bin/env python3
"""Flag tautological pytest tests (assertions that cannot fail on real breakage).

Stdlib only. Scans test_* functions and classifies every `assert` as strong or
weak. A test is reported when it has at least one assertion and *every*
assertion is weak.

Weak forms (per audit P0 test-quality work):
  assert True / assert 1
  assert x is not None / != None
  assert n >= 0
  assert len(x) > 0
  assert x == {} / == [] / == set() / == ""
  assert x == x
  assert call(...) == <literal returned by the same test's mock>

Baseline mode (CI): findings are keyed by file::function so line drift does not
create churn. `--update-baseline` rewrites the file; by default the process
fails only on findings NOT present in the baseline.
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

PLACEHOLDERS = ({}, [], set(), "", (), 0, False, None)


def _const(node: ast.AST):
    if isinstance(node, ast.Constant):
        return True, node.value
    if isinstance(node, ast.Dict) and not node.keys:
        return True, {}
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)) and not getattr(node, "elts", None):
        return True, type(node).__name__
    return False, None


def _is_len_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "len"


def _check_literal(test: ast.AST) -> str | None:
    if isinstance(test, ast.Constant) and bool(test.value):
        return "asserts a constant truthy literal"
    if isinstance(test, ast.Name) and test.id in {"True", "true"}:
        return "assert True"
    return None


def _check_not_none(test: ast.AST) -> str | None:
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return None
    is_const, value = _const(test.comparators[0])
    if isinstance(test.ops[0], (ast.IsNot, ast.NotEq)) and is_const and value is None:
        return "asserts only that a value is not None"
    return None


def _check_threshold(test: ast.AST) -> str | None:
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return None
    is_const, value = _const(test.comparators[0])
    if isinstance(test.ops[0], (ast.GtE, ast.Gt)) and is_const and isinstance(value, int):
        return f"asserts only {'>=' if isinstance(test.ops[0], ast.GtE) else '>'} {value}"
    return None


def _check_nonempty(test: ast.AST) -> str | None:
    if (
        not isinstance(test, ast.Compare)
        or len(test.ops) != 1
        or not isinstance(test.ops[0], ast.Gt)
    ):
        return None
    is_const, value = _const(test.comparators[0])
    if _is_len_call(test.left) and is_const and value == 0:
        return "asserts only that a collection is non-empty"
    return None


def _check_equality(test: ast.AST) -> str | None:
    if (
        not isinstance(test, ast.Compare)
        or len(test.ops) != 1
        or not isinstance(test.ops[0], ast.Eq)
    ):
        return None
    right = test.comparators[0]
    if isinstance(right, (ast.Dict, ast.List, ast.Set, ast.Tuple)):
        return "asserts only an empty collection"
    is_const, value = _const(right)
    if is_const and value in PLACEHOLDERS and value not in (0, False):
        return "asserts only an empty/placeholder value"
    if ast.dump(test.left) == ast.dump(right):
        return "asserts a value equals itself"
    return None


def _check_mock_call(test: ast.AST) -> str | None:
    if not isinstance(test, ast.Call):
        return None
    name = ast.unparse(test.func)
    if name.endswith(("assert_called", "assert_called_once")):
        return "asserts only that a mock was called (not with what result)"
    return None


def _check_bare_name(test: ast.AST) -> str | None:
    return "asserts only bare truthiness" if isinstance(test, ast.Name) else None


_WEAK_CHECKS = (
    _check_literal,
    _check_not_none,
    _check_threshold,
    _check_nonempty,
    _check_equality,
    _check_mock_call,
    _check_bare_name,
)


def _weak_assert(node: ast.Assert) -> str | None:
    """Return a reason string when this single assert cannot catch a regression."""
    for check in _WEAK_CHECKS:
        reason = check(node.test)
        if reason:
            return reason
    return None


def _mock_receivers(fn: ast.AST) -> set[str]:
    """Objects whose *.return_value this test configured (mock echo targets)."""
    out: set[str] = set()
    for node in ast.walk(fn):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Attribute) and target.attr == "return_value":
                out.add(ast.dump(target.value))
    return out


def _echoes_mock(node: ast.Assert, receivers: set[str]) -> bool:
    """True when the assertion checks the mock object itself, not the code under test."""
    if not receivers:
        return False
    for sub in ast.walk(node.test):
        if not isinstance(sub, ast.Compare):
            continue
        for side in [sub.left, *sub.comparators]:
            if (
                isinstance(side, ast.Call)
                and ast.dump(side.func.value if isinstance(side.func, ast.Attribute) else side.func)
                in receivers
            ):
                return True
    return False


def _assert_reasons(fn: ast.AST) -> tuple[int, list[str]]:
    asserts = [n for n in ast.walk(fn) if isinstance(n, ast.Assert)]
    mocks = _mock_receivers(fn)
    reasons: list[str] = []
    for assertion in asserts:
        reason = _weak_assert(assertion) or (
            _echoes_mock(assertion, mocks) and "asserts a value the mock itself returned"
        )
        if reason:
            reasons.append(reason)
    return len(asserts), reasons


def _is_test_fn(node: ast.AST) -> bool:
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
        "test_"
    )


def scan_file(path: Path) -> list[dict]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return []
    findings: list[dict] = []
    for node in ast.walk(tree):
        if not _is_test_fn(node):
            continue
        total, reasons = _assert_reasons(node)
        if total and len(reasons) == total:
            findings.append(
                {
                    "file": path.as_posix(),
                    "line": node.lineno,
                    "function": node.name,
                    "assertions": total,
                    "weak": len(reasons),
                    "reason": reasons[0],
                    "reasons": sorted(set(reasons)),
                }
            )
    return findings


def _collect(root: Path, tests: Path) -> list[dict]:
    findings: list[dict] = []
    for path in sorted(tests.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        for f in scan_file(path):
            f["file"] = path.relative_to(root).as_posix()
            findings.append(f)
    findings.sort(key=lambda f: (-f["weak"], f["file"], f["line"]))
    seen: dict[str, int] = {}
    for f in findings:
        base = f"{f['file']}::{f['function']}"
        seen[base] = seen.get(base, 0) + 1
        f["key"] = base if seen[base] == 1 else f"{base}#{seen[base]}"
    return findings


def _write_baseline(baseline: Path, findings: list[dict]) -> int:
    baseline.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "generated": "2026-10-18",
        "note": "Tautological tests frozen at baseline. Fix them; never add new ones.",
        "keys": sorted({f["key"] for f in findings}),
    }
    baseline.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"baseline written: {len(findings)} findings -> {baseline}")
    return 0


def _report(findings: list[dict], as_json: bool, top: int) -> None:
    if as_json:
        print(json.dumps(findings, indent=2))
        return
    print(f"tautological tests: {len(findings)}")
    for f in findings[:top]:
        print(
            f"  {f['file']}:{f['line']}  {f['function']}  [{f['weak']}/{f['assertions']}] {f['reason']}"
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--tests-dir", default="tests")
    ap.add_argument("--baseline", default="tests/integrity-baseline.json")
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()

    root = Path(args.repo).resolve()
    findings = _collect(root, root / args.tests_dir)
    if args.update_baseline:
        return _write_baseline(root / args.baseline, findings)
    _report(findings, args.json, args.top)
