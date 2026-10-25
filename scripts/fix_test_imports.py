#!/usr/bin/env python3
"""Normalise module-level imports in split test modules.

Deterministic replacement for hand patching the tiered test split:
  * each module-level import is emitted exactly once (duplicates dropped),
  * ``from __future__`` imports come first,
  * imports sit above module-level constants.

Refuses (and reports) any file whose imports sit below executable module-level
code, because hoisting those would change import order semantics.

Usage: python scripts/fix_test_imports.py <path> [<path> ...]
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path


def _is_docstring(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _is_constant_like(node: ast.stmt) -> bool:
    if not isinstance(node, (ast.Assign, ast.AnnAssign)):
        return False
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return all(
        isinstance(t, ast.Name) and (t.id.startswith("_") or t.id.isupper()) for t in targets
    )


def _block(nodes: list[ast.stmt]) -> list[str]:
    future = [n for n in nodes if isinstance(n, ast.ImportFrom) and n.module == "__future__"]
    rest = [n for n in nodes if n not in future]
    seen: set[str] = set()
    out: list[str] = []
    for node in [*future, *rest]:
        key = ast.unparse(node)
        if key in seen:
            continue
        seen.add(key)
        out.append(f"{key}\n")
    return out


def _prefix_end(body: list[ast.stmt], head_end: int) -> int:
    for number in range(head_end, len(body)):
        node = body[number]
        guarded = isinstance(node, (ast.Import, ast.ImportFrom)) or _is_constant_like(node)
        guarded = guarded or (
            isinstance(node, ast.If)
            and all(isinstance(s, (ast.Import, ast.ImportFrom)) for s in node.body)
        )
        if not guarded:
            return number
    return len(body)


def _rewrite(path: Path) -> str:
    source = path.read_text()
    lines = source.splitlines(keepends=True)
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return f"SYNTAX {path}: {exc}"
    body = tree.body
    head_end = 1 if body and _is_docstring(body[0]) else 0
    index = head_end
    while index < len(body) and isinstance(body[index], (ast.Import, ast.ImportFrom)):
        index += 1
    head = list(body[head_end:index])
    stop = _prefix_end(body, head_end)
    tail = [n for n in body[head_end:stop] if isinstance(n, (ast.Import, ast.ImportFrom))]
    late = [n for n in body[stop:] if isinstance(n, (ast.Import, ast.ImportFrom))]
    if late:
        return f"REFUSED {path}: import after code at line {late[0].lineno}"
    if not tail:
        return ""
    drop: set[int] = set()
    for node in [*head, *tail]:
        drop.update(range(node.lineno - 1, node.end_lineno))
    anchor = body[head_end - 1].end_lineno if head_end else 0
    kept = [line for number, line in enumerate(lines) if number >= anchor and number not in drop]
    out = [*lines[:anchor], *_block([*head, *tail]), "\n", *kept]
    path.write_text("".join(out))
    return f"FIXED {path}: moved {len(tail)} import(s)"


def main(argv: list[str]) -> int:
    targets = [Path(a) for a in argv[1:]]
    files = [p for t in targets for p in ([t] if t.is_file() else sorted(t.rglob("*.py")))]
    for path in files:
        message = _rewrite(path)
        if message:
            print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
