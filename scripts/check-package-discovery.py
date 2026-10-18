#!/usr/bin/env python3
"""check-package-discovery.py — packaging-discovery drift gate (all roots).

``[tool.setuptools.packages.find].include`` is an fnmatch glob list. setuptools
drops a pattern that matches nothing WITHOUT an error, so a stale entry builds
green and lies about what shipped. The inverse is worse: a real runtime package
under any ``where`` root that no pattern matches is silently left out of the
wheel — how seven root-level runtime packages went missing (P0, 2026-10-18).

Fails when: (a) a runtime-imported top-level package is not selected, (b) an
include pattern matches nothing under any root, (c) ``tests`` would ship,
(d) any other real package is matched by no pattern.

Resolution uses setuptools' own finders so the verdict matches the build.

Usage: python3 scripts/check-package-discovery.py [--repo .] [--json]
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import tomllib
from fnmatch import fnmatch
from pathlib import Path

EXIT_OK, EXIT_DRIFT, EXIT_UNMEASURABLE = 0, 1, 2
FIND_KEY = ("tool", "setuptools", "packages", "find")
# Runtime top-level packages the installed CLI/MCP entry points import. Explicit
# so deleting every import cannot quietly drop a package; absent ones (fixtures)
# are ignored.
REQUIRED_RUNTIME = (
    "pry",
    "pry_mcp",
    "extraction",
    "compliance",
    "site_catalog",
    "datasets",
    "actor_factory",
    "crypto_market",
)
FORBIDDEN = ("tests",)  # repository-only: never in the product artefact
SKIP_DIRS = {".git", ".venv", "venv", "build", "dist", "node_modules", "website", "__pycache__"}


def load_find_config(root: Path) -> dict:
    """Return [tool.setuptools.packages.find] as a dict, or {} when absent."""
    path = root / "pyproject.toml"
    if not path.exists():
        return {}
    node = tomllib.loads(path.read_text(encoding="utf-8"))
    for key in FIND_KEY:
        node = node.get(key, {}) if isinstance(node, dict) else {}
    return node if isinstance(node, dict) else {}


def discover(cfg: dict, root: Path) -> tuple[list[Path], list[str], list[str], set[str]]:
    """Return (where roots, namespace tree, selected packages, local top levels).

    The namespace tree is the build's view of each root (``namespaces`` unset =
    PEP 420), narrowed to packages whose top level is real local code — so root
    dirs such as ``scripts`` or ``docs`` are not mistaken for runtime packages.
    """
    from setuptools import find_namespace_packages, find_packages

    where = list(cfg.get("where") or ["."])
    include = list(cfg.get("include", [])) or ["*"]
    roots = [(root / w).resolve() for w in where]
    regular: set[str] = set()
    tree: set[str] = set()
    for base in roots:
        if base.is_dir():
            regular.update(find_packages(where=str(base), include=["*"]))
            tree.update(find_namespace_packages(where=str(base), include=["*"]))
    local = {p.split(".")[0] for p in regular}
    local |= {d.name for d in root.iterdir() if d.is_dir() and (d / "__init__.py").exists()}
    tree = sorted(p for p in tree if p.split(".")[0] in local)
    selected = sorted(
        p
        for base in roots
        if base.is_dir()
        for p in find_namespace_packages(where=str(base), include=include)
    )
    return roots, tree, selected, local


def scan_imports(root: Path, local: set[str]) -> set[str]:
    """Top-level local packages imported absolutely in src/ or a root package."""
    found: set[str] = set()
    bases = [root / "src"] + [root / name for name in sorted(local) if (root / name).is_dir()]
    for base in bases:
        for path in base.rglob("*.py"):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module]
                else:
                    continue
                found.update(n.split(".")[0] for n in names if n.split(".")[0] in local)
    return found


def classify(tree: list[str], patterns: list[str]) -> dict:
    """Bucket each pattern: exact hit, wildcard hit, or phantom (no hits)."""
    buckets: dict[str, list[str]] = {"exact": [], "wildcard": [], "phantom": []}
    for pattern in patterns:
        hits = [p for p in tree if fnmatch(p, pattern)]
        if not hits:
            buckets["phantom"].append(pattern)
        elif pattern in hits:
            buckets["exact"].append(pattern)
        else:
            buckets["wildcard"].append(pattern)
    return buckets


def report_and_fail(
    cfg: dict,
    roots: list[Path],
    tree: list[str],
    selected: list[str],
    imported: set[str],
    local: set[str],
) -> int:
    """Print the verdict; return the exit code."""
    selected_set = set(selected)
    selected_top = {p.split(".")[0] for p in selected}
    buckets = classify(tree, list(cfg.get("include", [])))
    required = ((set(REQUIRED_RUNTIME) | imported) & local) - selected_top
    shipped_tests = sorted(p for p in selected if p.split(".")[0] in FORBIDDEN)
    excluded = {p for p in tree if p.split(".")[0] in FORBIDDEN}
    omitted = [p for p in tree if p not in selected_set and p not in excluded]
    print(
        f"package-discovery gate: {len(tree)} discovered package(s) under "
        f"{', '.join(str(r) for r in roots)}; {len(selected)} selected "
        f"({len(buckets['exact'])} exact, {len(buckets['wildcard'])} wildcard, "
        f"{len(buckets['phantom'])} phantom); {len(imported)} runtime-imported top-level"
    )
    if not (buckets["phantom"] or omitted or required or shipped_tests):
        print("package-discovery gate: PASS")
        return EXIT_OK
    for label, items in (
        ("phantom include pattern(s) — setuptools drops these silently", buckets["phantom"]),
        ("runtime-imported top-level package(s) not selected", sorted(required)),
        ("tests would ship in the wheel", shipped_tests),
        ("real package(s) no include pattern matches", omitted),
    ):
        if items:
            print(f"\nFAIL ({label}):", file=sys.stderr)
            for item in items:
                print(f"  - {item}", file=sys.stderr)
    return EXIT_DRIFT


def main() -> int:
    """CLI entry: fail on phantom patterns, omitted packages, or a shipped tests/."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    root = Path(args.repo).resolve()
    cfg = load_find_config(root)
    if not cfg:
        print(
            f"package-discovery gate: FAIL (no [tool.setuptools.packages.find] "
            f"in {root / 'pyproject.toml'})",
            file=sys.stderr,
        )
        return EXIT_UNMEASURABLE
    roots, tree, selected, local = discover(cfg, root)
    if not tree:
        print(
            f"package-discovery gate: FAIL (resolved 0 packages under "
            f"where={cfg.get('where')} — nothing measured)",
            file=sys.stderr,
        )
        return EXIT_UNMEASURABLE
    imported = scan_imports(root, local) - set(FORBIDDEN)
    if args.json:
        print(
            json.dumps(
                {
                    "where": [str(r) for r in roots],
                    "discovered_packages": len(tree),
                    "selected_packages": len(selected),
                    "runtime_imported": sorted(imported),
                },
                indent=2,
            )
        )
    return report_and_fail(cfg, roots, tree, selected, imported, local)


if __name__ == "__main__":
    sys.exit(main())
