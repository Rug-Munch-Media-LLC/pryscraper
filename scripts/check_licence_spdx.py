#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
"""Fail when the SPDX-marked BSL-1.1 set drifts from LICENSE-BSL-STEALTH.

The BSL file list is legal-facing: a file added to (or removed from) the
stealth surface without a matching edit to LICENSE-BSL-STEALTH means the
distribution claims a licence it does not ship. This gate reads the actual
``SPDX-License-Identifier: BSL-1.1`` headers under ``src/`` and compares them
with the SPDX-BSL-FILE-LIST block in LICENSE-BSL-STEALTH.

stdlib only; runnable as ``python3 scripts/check_licence_spdx.py``.
Exit 0 = in sync, 1 = drift, 2 = the block is missing or malformed.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LICENCE_FILE = REPO_ROOT / "LICENSE-BSL-STEALTH"
SCAN_ROOT = REPO_ROOT / "src"
MARKER = "SPDX-License-Identifier: BSL-1.1"
SUFFIXES = frozenset({".py", ".js"})
BEGIN = "<!-- BEGIN SPDX-BSL-FILE-LIST -->"
END = "<!-- END SPDX-BSL-FILE-LIST -->"


def observed() -> set[str]:
    """Repo-relative paths of every source file carrying the BSL-1.1 marker."""
    found: set[str] = set()
    for path in SCAN_ROOT.rglob("*"):
        if path.suffix.lower() not in SUFFIXES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"error: cannot read {path}: {exc}", file=sys.stderr)
            continue
        if MARKER in text:
            found.add(path.relative_to(REPO_ROOT).as_posix())
    return found


def declared() -> set[str] | None:
    """Paths inside the SPDX-BSL-FILE-LIST block, or None if absent."""
    if not LICENCE_FILE.is_file():
        return None
    text = LICENCE_FILE.read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        return None
    body = text.split(BEGIN, 1)[1].split(END, 1)[0]
    entries: set[str] = set()
    for raw in body.splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            entries.add(line.lstrip("./"))
    return entries


def main(argv: list[str]) -> int:
    actual = observed()
    if "--list" in argv:
        for rel in sorted(actual):
            print(rel)
        return 0
    expected = declared()
    if expected is None:
        print(
            f"FAIL: {LICENCE_FILE.name} has no {BEGIN} ... {END} block",
            file=sys.stderr,
        )
        return 2
    missing = sorted(actual - expected)
    stale = sorted(expected - actual)
    if not missing and not stale:
        print(f"OK: {len(actual)} SPDX-BSL-1.1 files match {LICENCE_FILE.name}")
        return 0
    if missing:
        print("FAIL: marked BSL-1.1 in code but absent from LICENSE-BSL-STEALTH:")
        for rel in missing:
            print(f"  + {rel}")
    if stale:
        print("FAIL: listed in LICENSE-BSL-STEALTH but not marked BSL-1.1 in code:")
        for rel in stale:
            print(f"  - {rel}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
