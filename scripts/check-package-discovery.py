#!/usr/bin/env python3
"""check-package-discovery.py — packaging-discovery drift gate (all roots).

setuptools silently drops an ``include`` glob matching nothing (a stale entry
builds green) and omits an unmatched real runtime package from the wheel — how
seven root-level packages went missing (P0, 2026-10-18). Resolution uses
setuptools' own finders so the verdict matches the build.

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
# Runtime top-level packages the CLI/MCP entry points import; absent fixtures ignored.
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
    if not (root / "pyproject.toml").exists():
        return {}
    node = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    for key in FIND_KEY:
        node = node.get(key, {}) if isinstance(node, dict) else {}
    return node if isinstance(node, dict) else {}


def discover(cfg: dict, root: Path) -> tuple[list[Path], list[str], list[str], set[str]]:
    """Return (where roots, namespace tree, selected packages, local top levels).

    The tree is the build's view of each root (PEP 420), narrowed to packages
    whose top level is real local code (not dirs like ``scripts``/``docs``).
    """
    from setuptools import find_namespace_packages, find_packages

    where = list(cfg.get("where") or ["."])
    include = list(cfg.get("include", [])) or ["*"]
    roots = [(root / w).resolve() for w in where]
    regular, tree = set[str](), set[str]()
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


def _scan_root(base: Path, local: set[str]) -> set[str]:
    found: set[str] = set()
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
            found |= {n.split(".")[0] for n in names} & local
    return found


def scan_imports(root: Path, local: set[str]) -> set[str]:
    """Top-level local packages imported absolutely in src/ or a root package."""
    bases = [root / "src"] + [root / n for n in sorted(local) if (root / n).is_dir()]
    found: set[str] = set()
    for base in bases:
        found |= _scan_root(base, local)
    return found


def classify(tree: list[str], patterns: list[str]) -> dict:
    """Bucket each pattern: exact hit, wildcard hit, or phantom (no hits)."""
    buckets: dict[str, list[str]] = {"exact": [], "wildcard": [], "phantom": []}
    for pattern in patterns:
        hits = [p for p in tree if fnmatch(p, pattern)]
        key = "phantom" if not hits else ("exact" if pattern in hits else "wildcard")
        buckets[key].append(pattern)
    return buckets


def _check(d: dict) -> tuple[dict, dict[str, list[str]]]:
    selected = set(d["selected"])
    top = {p.split(".")[0] for p in selected}
    excluded = {p for p in d["tree"] if p.split(".")[0] in FORBIDDEN}
    buckets = classify(d["tree"], list(d["cfg"].get("include", [])))
    found = {
        "phantom include pattern(s) — setuptools drops these silently": buckets["phantom"],
        "runtime-imported top-level package(s) not selected": sorted(
            ((set(REQUIRED_RUNTIME) | d["imported"]) & d["local"]) - top
        ),
        "tests would ship in the wheel": sorted(
            p for p in selected if p.split(".")[0] in FORBIDDEN
        ),
        "real package(s) no include pattern matches": [
            p for p in d["tree"] if p not in selected and p not in excluded
        ],
    }
    return buckets, {label: items for label, items in found.items() if items}


def report_and_fail(d: dict) -> int:
    """Print the verdict; return the exit code."""
    buckets, failures = _check(d)
    print(
        f"package-discovery gate: {len(d['tree'])} discovered package(s) under "
        f"{', '.join(str(r) for r in d['roots'])}; {len(d['selected'])} selected "
        f"({len(buckets['exact'])} exact, {len(buckets['wildcard'])} wildcard, "
        f"{len(buckets['phantom'])} phantom); {len(d['imported'])} runtime-imported top-level"
    )
    if not failures:
        print("package-discovery gate: PASS")
        return EXIT_OK
    for label, items in failures.items():
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
            f"package-discovery gate: FAIL (no [tool.setuptools.packages.find] in "
            f"{root / 'pyproject.toml'})",
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
    return report_and_fail(
        {
            "cfg": cfg,
            "roots": roots,
            "tree": tree,
            "selected": selected,
            "imported": imported,
            "local": local,
        }
    )


if __name__ == "__main__":
    sys.exit(main())
