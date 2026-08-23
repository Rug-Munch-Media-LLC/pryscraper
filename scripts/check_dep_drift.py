#!/usr/bin/env python3
"""Dependency drift check: every requirements.txt package must be pinned in requirements.lock.

requirements.txt is the loose range manifest generated from pyproject.toml.
requirements.lock is the fully pinned install source (Dockerfile + CI).
If a dependency is added to pyproject/requirements.txt but the lock is not
regenerated, builds silently float on that package — this check fails CI
until the lock is refreshed.

Usage: python scripts/check_dep_drift.py   (exit 1 on drift)
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_NAME_RE = re.compile(r"^([a-zA-Z0-9][a-zA-Z0-9_.-]*)")


def _canonical(name: str) -> str:
    """PEP 503 name normalization."""
    return re.sub(r"[-_.]+", "-", name).lower()


def main() -> int:
    txt = REPO / "requirements.txt"
    lock = REPO / "requirements.lock"
    if not txt.exists() or not lock.exists():
        print(f"missing {txt.name} or {lock.name}")
        return 1

    declared: set[str] = set()
    for line in txt.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _NAME_RE.match(line)
        if m:
            declared.add(_canonical(m.group(1)))

    pinned: set[str] = set()
    for line in lock.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _NAME_RE.match(line)
        if m and "==" in line:
            pinned.add(_canonical(m.group(1)))

    drifted = sorted(declared - pinned)
    if drifted:
        print("DRIFT: packages declared but not pinned in requirements.lock:")
        for name in drifted:
            print(f"  - {name}")
        print("\nRegenerate: .venv/bin/pip freeze > requirements.lock")
        return 1

    print(f"OK: all {len(declared)} declared packages are pinned in requirements.lock")
    return 0


if __name__ == "__main__":
    sys.exit(main())
