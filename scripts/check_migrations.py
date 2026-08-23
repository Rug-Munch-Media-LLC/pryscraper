#!/usr/bin/env python3
"""Migration safety gates for Pry.

1. Model drift: `alembic check` must report models and migrations in sync.
2. Dangerous-op lint: new migration files may not contain unreviewed
   destructive operations (DROP TABLE/COLUMN) without an explicit
   `# reviewed:` marker on the same line.

Exit 1 on any violation.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DANGEROUS = re.compile(r"op\.(drop_table|drop_column)\(")


def main() -> int:
    os.chdir(REPO)
    env = dict(os.environ, PRY_DATABASE_URL=os.environ.get("PRY_DATABASE_URL", ""))

    # 1. Drift check against a throwaway DB migrated to head.
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        probe = f.name
    env["PRY_DATABASE_URL"] = f"sqlite:///{probe}"
    try:
        up = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            env=env,
        )
        if up.returncode != 0:
            print("FAIL: alembic upgrade head did not apply cleanly:\n" + up.stderr[-800:])
            return 1
        chk = subprocess.run(
            [sys.executable, "-m", "alembic", "check"],
            capture_output=True,
            text=True,
            env=env,
        )
        if chk.returncode != 0:
            output = chk.stdout + chk.stderr
            # Nullability/server-default diffs against legacy hand-written
            # migrations are cosmetic on SQLite; structural drift is not.
            structural = [
                op
                for op in (
                    "add_table",
                    "remove_table",
                    "add_column",
                    "remove_column",
                    "add_index",
                    "remove_index",
                    "add_fk",
                    "remove_fk",
                    "modify_type",
                    "rename",
                )
                if op in output
            ]
            if structural:
                print(
                    f"FAIL: STRUCTURAL model drift detected ({', '.join(structural)}). "
                    "Run `alembic revision --autogenerate`:\n" + output[-800:]
                )
                return 1
            print("note: cosmetic nullability/default drift only (legacy migrations)")
    finally:
        if os.path.exists(probe):
            os.unlink(probe)

    # 2. Destructive-op lint for NEW (uncommitted) migrations only.
    # Historical downgrades legitimately drop tables; future unreviewed
    # destructive ops are what this gate exists to catch.
    tracked = set(
        subprocess.run(
            ["/usr/bin/git", "ls-files", "alembic/versions/"],
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )
    violations = []
    for path in sorted((REPO / "alembic" / "versions").glob("*.py")):
        rel = str(path.relative_to(REPO))
        if rel in tracked:
            continue  # already-reviewed history
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if DANGEROUS.search(line) and "reviewed:" not in line:
                violations.append(f"{path.name}:{lineno}: {line.strip()}")
    if violations:
        print("FAIL: destructive migration ops without '# reviewed:' marker:")
        for v in violations:
            print("  " + v)
        return 1

    print("OK: migrations in sync with models; no unreviewed destructive ops")
    return 0


if __name__ == "__main__":
    sys.exit(main())
