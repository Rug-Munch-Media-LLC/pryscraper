#!/usr/bin/env python3
"""Generate a byte-stable ``openapi.json`` from the Pry FastAPI app.

Stdlib only (``json`` + the app import). No network, no DB: importing the
app does not open connections — it only assembles routes.

Determinism is guaranteed by:
  * a deterministic admin path prefix (``admin_router`` reads env, with a
    STABLE dev default rather than a random per-boot token), and
  * sorted keys + fixed indent + trailing newline on write.

Usage:  python3 scripts/gen_openapi.py
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "openapi.json"


def _ensure_import_path() -> None:
    """Prepend the repo ``src`` and root so this works from any worktree.

    ``pry`` lives under ``src/`` and the top-level ``extraction`` package at
    the repo root; running the script directly puts ``scripts/`` first on
    ``sys.path``, so both must be added explicitly.
    """
    for entry in (str(ROOT / "src"), str(ROOT)):
        if entry not in sys.path:
            sys.path.insert(0, entry)


def generate() -> dict:
    """Build the OpenAPI spec from the assembled app (no I/O side effects)."""
    _ensure_import_path()
    from pry.api.api import app

    return app.openapi()


def main() -> None:
    spec = generate()
    payload = json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False)
    OUTPUT.write_text(payload + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT} ({len(spec.get('paths', {}))} paths)")


if __name__ == "__main__":
    main()
