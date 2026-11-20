#!/usr/bin/env python3
"""Regenerate requirements.docker.lock from uv.lock (runtime deps only).

WHY THIS READS uv.lock, NOT requirements.lock

The previous version filtered ``requirements.lock`` through a hardcoded
dev-package list. That list was incomplete, and the failure mode was not a
cosmetic drift -- the image stopped building entirely:

    ResolutionImpossible: The user requested mcp==2.3.0
                          semgrep 1.182.1 depends on mcp==1.29.0

``semgrep`` is a DEV/TEST scanner that has no business in a runtime image. It
was absent from the block-list, so it was copied in, and its old ``mcp`` pin
collided with the ``mcp>=2.0`` this project actually requires. Adding it to the
list would fix today's instance and leave the same trap for the next dev tool.

Instead, derive the runtime set from the resolver itself: ``uv export`` without
``--all-extras --all-groups`` emits exactly the project's runtime dependencies,
so a dev tool cannot reach the image no matter what anyone forgets to block.

CI drift-checks this file (``docker lock drift check``), so the output must be
deterministic: sorted by name, one pin per line, no hashes.
"""

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DST = REPO / "requirements.docker.lock"

HEADER = (
    "# Generated from uv.lock (runtime deps only) - DO NOT EDIT.\n"
    "# Regenerate: python3 scripts/gen-docker-lock.py\n"
    "#\n"
    "# This is the project's RUNTIME dependency closure, projected from uv.lock\n"
    "# by `uv export` with no extras and no groups. Dev/test tools (pytest,\n"
    "# semgrep, mutmut, ...) are excluded by construction rather than by a\n"
    "# hand-maintained block-list, because a missing entry there once put\n"
    "# semgrep into the image and broke the build on a conflicting mcp pin.\n"
)


def main() -> int:
    try:
        out = subprocess.run(
            [
                "uv",
                "export",
                "--frozen",
                "--no-hashes",
                "--no-emit-project",
                "-o",
                "-",
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        print(f"gen-docker-lock: uv export failed: {detail.strip()[:400]}", file=sys.stderr)
        return 1

    pins: dict[str, str] = {}
    for line in out.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("-") or "==" not in s:
            continue
        name = s.split("==")[0].split("[")[0].strip()
        pins[name.lower().replace("_", "-")] = s

    DST.write_text(HEADER + "\n".join(sorted(pins.values(), key=str.lower)) + "\n")
    print(f"wrote {len(pins)} pins -> {DST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
