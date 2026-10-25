# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Import guard: rate-limit / extractor / retry modules have ONE owner each.

A new ``rate_limit_v2.py`` (or a second extractor/retry module) re-creates the
duplication this repo already paid for: 19 rate-limit copies and 17 extractor
copies. New modules must be added to ``CANONICAL`` with a reason, and every
entry must still exist (shrink-only allowlist).
"""

from __future__ import annotations

import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "pry"

# Shrink-only: add an entry only with a reason a reviewer accepts.
CANONICAL: dict[str, str] = {
    "core/ratelimit.py": "inbound per-IP bucket (Redis + memory)",
    "core/outbound_politeness.py": "outbound per-key spacing + capped backoff",
    "engine/extractor.py": "canonical schema extractor",
    "engine/retry.py": "retry policy + backoff math",
    "engine/email_scraper/extractor.py": "email-pattern extractor (own domain)",
}

PATTERN = re.compile(r"^(rate_?limit|extractor|retry)")


def _modules() -> list[pathlib.Path]:
    return [
        p
        for p in SRC.rglob("*.py")
        if "__pycache__" not in p.parts and PATTERN.search(p.stem)
    ]


def test_no_unauthorised_rate_limit_extractor_retry_module():
    offenders = sorted(str(p.relative_to(SRC)) for p in _modules())
    unknown = [rel for rel in offenders if rel not in CANONICAL]
    assert unknown == [], (
        "utility module outside a canonical path: "
        f"{unknown}. Reuse the canonical module or add it to CANONICAL with a reason."
    )


def test_allowlist_has_no_dead_entries():
    missing = [rel for rel in CANONICAL if not (SRC / rel).is_file()]
    assert missing == [], f"stale allowlist entries (shrink-only): {missing}"
