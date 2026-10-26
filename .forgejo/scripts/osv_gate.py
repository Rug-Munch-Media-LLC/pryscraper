#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
"""Block CI on CRITICAL/HIGH OSV advisories in uv.lock.

UNKNOWN (no categorical severity, e.g. a bare CVSS vector) is blocking: an
unclassifiable advisory must not be treated as low risk.
"""
import json
import sys
from pathlib import Path

BLOCKING = frozenset({"CRITICAL", "HIGH", "UNKNOWN"})


def main(path: str) -> int:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    hits: list[str] = []
    counts: dict[str, int] = {}
    for result in data.get("results", []):
        for package in result.get("packages", []):
            name = (package.get("package") or {}).get("name")
            for vuln in package.get("vulnerabilities", []):
                raw = (vuln.get("database_specific") or {}).get("severity")
                sev = str(raw or "UNKNOWN").upper()
                counts[sev] = counts.get(sev, 0) + 1
                if sev in BLOCKING:
                    hits.append(f"{sev} {name} {vuln.get('id')}")
    sys.stdout.write(f"osv severity histogram: {counts or {'NONE': 0}}\n")
    if hits:
        sys.stdout.write("BLOCKING advisories:\n")
        for hit in hits:
            sys.stdout.write(f"  {hit}\n")
        return 1
    sys.stdout.write("gate: no CRITICAL/HIGH/UNKNOWN advisories\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "osv.json"))
