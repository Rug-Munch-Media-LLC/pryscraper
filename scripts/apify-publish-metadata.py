#!/usr/bin/env python3
"""Apply Store publication metadata to every deployed Pry actor.

Sweeps all Actor Factory presets and issues one ``PUT /v2/acts/:actorId``
per actor carrying title, description, ``isPublic: true``, its store
category, and the PAY_PER_EVENT pricing record built from the preset's
pricing events. This is the step ``apify push`` cannot do: the platform
rejects ``isPublic`` without ``categories`` (schema-validation), and
monetization requires a ``pricingInfos`` record.

Account-level prerequisites (one-time Console actions, no API exists):
  1. Accept the Apify Store Publishing Terms as the org owner.
  2. Set payout billing info (console.apify.com -> Monetization).
Until both are done every PUT answers 403/400; this script reports the
platform message verbatim per actor instead of masking it.

Usage:
    python scripts/apify-publish-metadata.py --dry-run   # print payloads
    python scripts/apify-publish-metadata.py             # apply all
    python scripts/apify-publish-metadata.py --only universal-scraper

Exit codes: 0 = all requested actors updated, 1 = one or more failures,
2 = prerequisite error (missing token / unknown preset).
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from actor_factory.metadata import (  # noqa: E402
    APIFY_VALID_CATEGORIES,
    build_publication_payload,
    category_for,
    publish_metadata,
)
from actor_factory.presets import ALL_PRESETS  # noqa: E402


def _resolve_token() -> str:
    """Token precedence: APIFY_TOKEN env > gopass org token."""
    env = os.environ.get("APIFY_TOKEN", "").strip()
    if env:
        return env
    import shutil
    import subprocess

    gopass = shutil.which("gopass")
    if not gopass:
        print(
            "ERROR: no Apify token. Set APIFY_TOKEN or install gopass (rmi/infra/apify_org_token).",
            file=sys.stderr,
        )
        raise SystemExit(2)
    proc = subprocess.run(  # noqa: S603 - resolved absolute path, fixed argv
        [gopass, "show", "-o", "rmi/infra/apify_org_token"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    token = (proc.stdout or "").strip()
    if proc.returncode == 0 and token:
        return token
    print(
        "ERROR: no Apify token. Set APIFY_TOKEN or unlock gopass (rmi/infra/apify_org_token).",
        file=sys.stderr,
    )
    raise SystemExit(2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        nargs="*",
        help="apply only these preset names (with or without pry- prefix)",
    )
    parser.add_argument("--dry-run", action="store_true", help="print payloads, no API calls")
    parser.add_argument("--org", default="rugmunchmedia", help="org/user owning the actors")
    args = parser.parse_args()

    names = sorted(ALL_PRESETS)
    if args.only:
        wanted = {n.removeprefix("pry-") for n in args.only}
        names = [n for n in names if n.removeprefix("pry-") in wanted]
        unknown = wanted - {n.removeprefix("pry-") for n in ALL_PRESETS}
        if unknown:
            print(f"ERROR: unknown preset(s): {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2

    # Fail fast on mapping integrity before touching the API.
    bad = [n for n in names if category_for(n) not in APIFY_VALID_CATEGORIES]
    if bad:
        print(f"ERROR: invalid categories mapped for: {bad}", file=sys.stderr)
        return 2

    if args.dry_run:
        for name in names:
            spec = ALL_PRESETS[name]
            payload = build_publication_payload(spec)
            print(f"{spec.name}:")
            print(json.dumps(payload, indent=2)[:400])
        return 0

    token = _resolve_token()
    failures = 0
    blockers: dict[str, int] = {}
    for name in names:
        spec = ALL_PRESETS[name]
        ok, detail = publish_metadata(spec, token, org=args.org)
        mark = "OK " if ok else "FAIL"
        print(f"[{mark}] {spec.name}: {detail}", flush=True)
        if not ok:
            failures += 1
            # Group identical account-level blockers so the operator sees
            # one action item, not 94 copies.
            key = detail.split(": ", 1)[-1][:120]
            blockers[key] = blockers.get(key, 0) + 1

    if blockers:
        print("\nACCOUNT-LEVEL BLOCKERS (fix once in Console, then re-run):")
        for msg, count in sorted(blockers.items(), key=lambda kv: -kv[1]):
            print(f"  x{count}: {msg}")
    print(f"\n{len(names) - failures}/{len(names)} updated, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
