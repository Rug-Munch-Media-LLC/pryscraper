#!/usr/bin/env python3
"""check-package-discovery.py — packaging-discovery drift gate (both directions).

``[tool.setuptools.packages.find].include`` is a glob list that setuptools
applies with ``fnmatch``. Patterns that match nothing are dropped WITHOUT an
error, so a stale or invented entry compiles, ships a wheel, and only fails
later at import time. The inverse is worse: a real package under the ``where``
root that no pattern matches is silently excluded from the distribution.

This gate asserts the include list resolves to EXACTLY the set of real packages
under the discovery roots — it fails on a phantom pattern (matches nothing) and
on an omission (a real package matched by no pattern), which are the two halves
of the same defect.

Resolution deliberately goes through ``setuptools.config.expand.find_packages``
— the exact callable the build backend uses — so the verdict matches the wheel
rather than a hand-rolled glob.

Usage:
  python3 scripts/check-package-discovery.py [--repo .] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from fnmatch import fnmatch
from pathlib import Path

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_UNMEASURABLE = 2  # reserved: the gate could not measure (never report PASS)

FIND_KEY = ("tool", "setuptools", "packages", "find")


def load_find_config(root: Path) -> dict:
    """Return [tool.setuptools.packages.find] as a dict, or {} when absent."""
    path = root / "pyproject.toml"
    if not path.exists():
        return {}
    node = tomllib.loads(path.read_text(encoding="utf-8"))
    for key in FIND_KEY:
        node = node.get(key, {}) if isinstance(node, dict) else {}
    return node if isinstance(node, dict) else {}


def resolve(root: Path, cfg: dict) -> tuple[list[str], list[str]]:
    """Return (real packages, packages the include list actually selects).

    ``real`` is every package setuptools would discover with the include list
    removed; ``selected`` is the result the build resolves with it applied.
    ``namespaces`` is left unset to mirror the build default (PEP 420 enabled).
    """
    from setuptools.config.expand import find_packages

    kwargs: dict = {"where": cfg.get("where", ["."]), "root_dir": str(root)}
    include = list(cfg.get("include", [])) or ["*"]
    real = find_packages(include=["*"], **kwargs)
    selected = find_packages(include=include, **kwargs)
    return sorted(real), sorted(selected)


def classify(real: list[str], selected: list[str], patterns: list[str]) -> dict:
    """Bucket each include pattern and list the packages nothing matches."""
    buckets = {"real": [], "phantom": [], "ambiguous": []}
    for pattern in patterns:
        hits = [p for p in real if fnmatch(p, pattern)]
        if not hits:
            buckets["phantom"].append(pattern)
        elif pattern in hits:
            buckets["real"].append(pattern)
        else:
            # Matches real packages only through a wildcard: correct, but not a
            # literal one-to-one name, so it is reported apart from exact hits.
            buckets["ambiguous"].append(pattern)
    selected_set = set(selected)
    buckets["omitted"] = [p for p in real if p not in selected_set]
    return buckets


def main() -> int:
    """CLI entry: fail on a phantom include pattern or an omitted real package."""
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

    real, selected = resolve(root, cfg)
    if not real:
        print(
            f"package-discovery gate: FAIL (resolved 0 packages under "
            f"where={cfg.get('where')} — nothing was measured)",
            file=sys.stderr,
        )
        return EXIT_UNMEASURABLE

    buckets = classify(real, selected, list(cfg.get("include", [])))
    report = {
        "real_packages": len(real),
        "selected_packages": len(selected),
        "phantom_patterns": buckets["phantom"],
        "exact_patterns": buckets["real"],
        "wildcard_patterns": buckets["ambiguous"],
        "omitted_packages": buckets["omitted"],
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(
            f"package-discovery gate: {len(real)} real package(s) under "
            f"{', '.join(cfg.get('where', ['.']))}; {len(selected)} selected "
            f"({len(buckets['real'])} exact pattern(s), "
            f"{len(buckets['ambiguous'])} wildcard, "
            f"{len(buckets['phantom'])} phantom)"
        )

    failed = bool(buckets["phantom"] or buckets["omitted"])
    if failed:
        if buckets["phantom"]:
            where = ", ".join(cfg.get("where", ["."]))
            print(
                f"\nFAIL (phantom include pattern(s) — setuptools drops these "
                f"silently under {where}):",
                file=sys.stderr,
            )
            for pattern in buckets["phantom"]:
                print(f"  - {pattern}", file=sys.stderr)
        if buckets["omitted"]:
            print("\nFAIL (real package(s) no include pattern matches):", file=sys.stderr)
            for name in buckets["omitted"]:
                print(f"  - {name}", file=sys.stderr)
        return EXIT_DRIFT

    print("package-discovery gate: PASS")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
