#!/usr/bin/env python3
"""Regenerate requirements.docker.lock from requirements.lock.

Drops dev/test dependencies (pact, pytest, mutmut...) whose transitive
pins conflict on a cold resolve. CI drift-checks this file.
"""

import re
from pathlib import Path

BLOCK = re.compile(
    r"^(pact|pytest|mutmut|hypothesis|vulture|radon|interrogate|locust|bandit"
    r"|pre-commit|coverage|ruff|mypy|pyright|tox|sphinx|mkdocs)",
)
src = Path(__file__).resolve().parents[1] / "requirements.lock"
dst = src.parent / "requirements.docker.lock"
kept = []
for line in src.read_text().splitlines():
    s = line.strip()
    if not s or s.startswith(("#", "-")) or "git+" in s:
        continue
    name = s.split("==")[0].split("[")[0].replace("-", "_").lower()
    if not BLOCK.match(name):
        kept.append(s)
header = "# Generated from requirements.lock minus dev/test deps - DO NOT EDIT.\n"
dst.write_text(header + "\n".join(sorted(kept)) + "\n")
print(f"wrote {len(kept)} pins -> {dst}")
