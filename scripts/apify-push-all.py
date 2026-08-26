#!/usr/bin/env python3
"""Push all Actor Factory presets to the Apify platform.

Stages every preset under a staging root, validates the package, then runs
`apify push` per actor via apify-cli. Requires `apify login` beforehand
(the CLI v1.x reads auth from its stored login state, not env vars).

Usage:
    python scripts/apify-push-all.py --dry-run
    python scripts/apify-push-all.py --only pry-recipe-miner
    python scripts/apify-push-all.py --resume   # skip already-pushed
    python scripts/apify-push-all.py            # full batch

Exit codes: 0 = all requested actors ok, 1 = one or more failures,
2 = prerequisite/auth error.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from actor_factory.publish import run_batch  # noqa: E402

logger = logging.getLogger("apify-push-all")


def _make_org_push(org: str, token: str):
    """Wrap push_actor with create-if-missing for first-time org uploads.

    apify-cli v1.x cannot create an actor when an explicit ID is passed;
    it only updates existing ones. We ensure existence via API v2 first,
    then hand off to the normal staged push.
    """
    import json as _json
    import subprocess as _sp

    def _push(stage, actor_id=None):
        """Ensure actor exists (API), then CLI push from staged dir.

        CLI v1.x 'push <id>' cannot create and silently no-ops source
        uploads on some updates; 'push --force --dir' from the package
        root is the documented reliable path once the actor exists.
        """
        store_name = stage.name.removeprefix("pry-")
        aid = f"{org}~{store_name}"
        meta = _json.loads((stage / ".actor" / "actor.json").read_text())

        def api(method, path, payload=None):
            cmd = [
                "curl",
                "-sfS",
                "-m",
                "60",
                "-X",
                method,
                "-H",
                f"Authorization: Bearer {token}",
                "-H",
                "Content-Type: application/json",
            ]
            if payload is not None:
                cmd += ["-d", _json.dumps(payload)]
            cmd += [f"https://api.apify.com/v2{path}"]
            r = _sp.run(cmd, capture_output=True)  # noqa: S603 - fixed argv
            r.stdout = (r.stdout or b"").decode("utf-8", "replace")
            r.stderr = (r.stderr or b"").decode("utf-8", "replace")
            if r.returncode != 0:
                print(
                    f"[api FAIL {method} {path}]", (r.stdout or r.stderr or "")[-200:], flush=True
                )
            return r

        chk = api("GET", f"/acts/{aid}")
        if chk.returncode != 0:
            cr = api(
                "POST",
                "/acts",
                {
                    "name": store_name,
                    "title": meta.get("title", store_name),
                    "description": meta.get("description", ""),
                    "isPublic": True,
                },
            )
            if cr.returncode != 0:
                return False, f"create failed: {(cr.stdout or cr.stderr)[-200:]}"

        npx_path = "npx"

        pr = _sp.run(  # noqa: S603 - fixed argv
            [npx_path, "--yes", "apify-cli", "push", "--force", "--dir", str(stage)],
            capture_output=True,
            timeout=600,
        )
        pr.stdout = (pr.stdout or b"").decode("utf-8", "replace")
        pr.stderr = (pr.stderr or b"").decode("utf-8", "replace")
        if pr.returncode != 0:
            return False, f"cli push failed: {(pr.stdout or pr.stderr)[-300:]}"

        # Metadata PUT (cli does not backfill title/description reliably)
        mr = api(
            "PUT",
            f"/acts/{aid}",
            {
                "title": meta.get("title", store_name),
                "description": meta.get("description", ""),
                "isPublic": True,
            },
        )
        return True, f"pushed{'' if mr.returncode == 0 else ' (meta put failed)'}"

    return _push


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--staging-root",
        type=Path,
        default=Path(tempfile.gettempdir()) / "opencode" / "apify-staging",
        help="where staged packages + results.json live (default: <tmpdir>/opencode/apify-staging)",
    )
    parser.add_argument("--only", nargs="*", help="push only these preset names")
    parser.add_argument("--dry-run", action="store_true", help="stage+validate only, no upload")
    parser.add_argument("--resume", action="store_true", help="skip presets already pushed ok")
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="seconds between pushes (default: 2.0)",
    )
    parser.add_argument(
        "--org",
        default=None,
        help="Apify org username/slug - pushes as org~actor-name (for org-owned catalogs)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    failures: list[str] = []
    count = 0
    try:
        for result in run_batch(
            REPO,
            args.staging_root,
            only=args.only,
            dry_run=args.dry_run,
            resume=args.resume,
            delay_seconds=args.delay,
            actor_id_prefix=args.org,
            push_fn=(
                _make_org_push(args.org, os.environ["APIFY_TOKEN"])
                if args.org and not args.dry_run and os.environ.get("APIFY_TOKEN")
                else None
            ),
        ):
            count += 1
            if not result.ok:
                failures.append(result.name)
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 2

    mode = "staged" if args.dry_run else "processed"
    logger.info("%d actors %s, %d failures", count, mode, len(failures))
    if failures:
        logger.error("failed: %s", ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
