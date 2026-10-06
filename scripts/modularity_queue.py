#!/usr/bin/env python3
"""Rank source files for modularisation and say how each one should be split.

Triage is mechanical so nobody has to re-derive it: a module whose functions
barely touch ``self`` is a bag of independent helpers and can be extracted
into a package. One with many ``self.`` references is object behaviour, and
moving its methods out breaks them — it needs composition instead, which is
a redesign and belongs in its own change.

Usage:
    python3 scripts/modularity_queue.py                  # top 40
    python3 scripts/modularity_queue.py --extract       # only extractable
    python3 scripts/modularity_queue.py --compose       # only redesigns
    python3 scripts/modularity_queue.py --json           # machine readable
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
import pathlib

logger = logging.getLogger(__name__)

CAP = 200
SELF_THRESHOLD = 3
ROOT = pathlib.Path(__file__).resolve().parent.parent
SEARCH = ("src", "pry_mcp", "datasets")


def analyse(path: pathlib.Path) -> dict[str, object] | None:
    try:
        src = path.read_text(errors="ignore")
    except OSError as e:
        logger.warning(
            "suppressed %s in analyse (modularity_queue.py:37): %s",
            "OSError",
            e,
        )
        return None
    lines = len(src.splitlines())
    if lines <= CAP:
        return None
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        logger.warning(
            "suppressed %s in analyse (modularity_queue.py:44): %s",
            "SyntaxError",
            e,
        )
        return {
            "file": str(path.relative_to(ROOT)),
            "lines": lines,
            "strategy": "unparsed",
            "self_refs": -1,
        }
    self_refs = sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    )
    return {
        "file": str(path.relative_to(ROOT)),
        "lines": lines,
        "self_refs": self_refs,
        "classes": sum(1 for n in tree.body if isinstance(n, ast.ClassDef)),
        "functions": sum(
            1 for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ),
        "strategy": "extract" if self_refs < SELF_THRESHOLD else "compose",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--extract", action="store_true")
    ap.add_argument("--compose", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args()

    rows = [
        r
        for d in SEARCH
        if (ROOT / d).exists()
        for r in [analyse(p) for p in (ROOT / d).rglob("*.py")]
        if r
    ]
    if args.extract:
        rows = [r for r in rows if r.get("strategy") == "extract"]
    elif args.compose:
        rows = [r for r in rows if r.get("strategy") == "compose"]
    rows.sort(key=lambda r: -int(r["lines"]))

    if args.json:
        print(json.dumps({"cap": CAP, "total": len(rows), "files": rows}, indent=2))
        return 0

    ex = sum(1 for r in rows if r.get("strategy") == "extract")
    co = sum(1 for r in rows if r.get("strategy") == "compose")
    print(f"over {CAP} lines: {len(rows)}  (extract {ex}, compose {co})")
    print()
    for r in rows[: args.limit]:
        tag = "EXTRACT" if r.get("strategy") == "extract" else f"compose/{r['self_refs']}self"
        print(f"{int(r['lines']):5d}  {r['file']:58s} {tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
