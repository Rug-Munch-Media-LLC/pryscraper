#!/usr/bin/env python3
"""Dedicated monkeypatch ratchet gate (decrease-only).

docs/MODERNIZATION.md §2.3 / §4.3: the repo-wide monkeypatch count may never
increase. This gate is deliberately separate from the aggregate
``check-antipatterns.py`` baseline so that an unrelated change cannot inflate
the monkeypatch budget while other rules shrink to compensate.

Counts monkeypatch-attribute access, mock-patch calls, patch decorators,
patch-object calls and sys.modules deletions (Python sources only).
The matched patterns live in ``MONKEY_RE`` below.

Usage:
  python3 scripts/check-monkeypatch --repo .                 # gate
  python3 scripts/check-monkeypatch --repo . --update-baseline
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import NoReturn

DEFAULT_BASELINE = "scripts/monkeypatch-baseline.json"

# Exit 2 is reserved and means one thing only: the gate could not measure.
#   0 = measured, within budget (pass)
#   1 = measured, over budget (the ratchet moved)
#   2 = could not load the baseline, so nothing was measured
# A CI job must be able to tell the last one apart from the first two.
BASELINE_UNREADABLE = 2
MONKEY_RE = re.compile(r"monkeypatch\.|mock\.patch|@patch\(|patch\.object|del sys\.modules")

SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "site-packages",
    "mutants",
    ".tox",
    ".nox",
    "htmlcov",
}


def scan(root: Path) -> tuple[int, dict[str, int]]:
    """Return (total occurrences, per-file counts for files with matches)."""
    total = 0
    per_file: dict[str, int] = {}
    for p in root.rglob("*.py"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        try:
            lines = p.read_text(errors="ignore").splitlines()
        except OSError:
            continue
        n = sum(1 for ln in lines if MONKEY_RE.search(ln))
        if n:
            rel = p.relative_to(root).as_posix()
            per_file[rel] = n
            total += n
    return total, per_file


def _unreadable(reason: str) -> NoReturn:
    """Print why the gate could not measure, then exit 2 (never 0, never 1)."""
    print(
        f"check-monkeypatch: cannot measure — {reason}\n"
        f"  This is NOT a pass and NOT a measured failure. The monkeypatch ratchet\n"
        f"  was not evaluated because the baseline is unusable. Fix the baseline\n"
        f"  ({DEFAULT_BASELINE}) or pass --baseline <path>. Exiting {BASELINE_UNREADABLE}.",
        file=sys.stderr,
    )
    raise SystemExit(BASELINE_UNREADABLE)


def load_baseline(path: Path) -> int:
    """Read the decrease-only monkeypatch baseline from JSON.

    Fails CLOSED. A missing or malformed baseline previously defaulted to 0,
    which made the gate report PASS while measuring nothing — false
    confidence in a repo that carries a four-figure monkeypatch count. All
    three malformed cases (unreadable file, invalid JSON, wrong shape) now
    exit BASELINE_UNREADABLE so a CI job can distinguish "could not measure"
    from "measured and found a problem".
    """
    if not path.exists():
        _unreadable(f"baseline file not found: {path}")
    try:
        raw = path.read_text()
    except OSError as exc:
        _unreadable(f"baseline file is unreadable: {path} ({exc.strerror or exc})")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        _unreadable(f"baseline file is not valid JSON: {path} (line {exc.lineno}, col {exc.colno})")
    if not isinstance(data, dict) or not isinstance(data.get("total"), int):
        _unreadable(
            f"baseline has the wrong shape: {path} (expected an object with an int 'total')"
        )
    return data["total"]


def main() -> int:
    """CLI entry: count monkeypatches and enforce the shrink-only ratchet."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--baseline", default=DEFAULT_BASELINE)
    ap.add_argument("--update-baseline", action="store_true")
    args = ap.parse_args()

    root = Path(args.repo).resolve()
    baseline_path = root / args.baseline

    if args.update_baseline:
        # A raise is the ratchet's purpose, so an absent or unusable baseline is
        # a legitimate bootstrap here and is NOT a fail-closed condition.
        bootstrap = not baseline_path.exists()
        base = 0 if bootstrap else load_baseline(baseline_path)
        total, per_file = scan(root)
        if total > base and not bootstrap:
            print(f"REFUSING to raise the monkeypatch baseline: {base} -> {total}")
            return 1
        baseline_path.write_text(
            json.dumps({"total": total, "files": dict(sorted(per_file.items()))}, indent=1) + "\n"
        )
        print(f"monkeypatch baseline updated: {baseline_path} (total {total})")
        return 0

    # Loaded before the scan: an unusable baseline is fatal, and there is no
    # point walking the tree if the ratchet cannot be evaluated anyway.
    base = load_baseline(baseline_path)
    total, per_file = scan(root)

    print(f"monkeypatch gate: {total} occurrences (baseline {base})")
    for rel, n in sorted(per_file.items(), key=lambda x: -x[1])[:10]:
        print(f"  {n:>4}  {rel}")
    if total > base:
        print(f"\nFAIL (monkeypatch ratchet): {base} -> {total} — decrease-only, fix don't add")
        return 1
    print("monkeypatch gate: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
