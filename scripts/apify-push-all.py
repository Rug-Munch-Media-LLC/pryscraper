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

    from actor_factory.publish import push_actor

    def _push(stage, actor_id=None):
        """API v2 deploy: ensure -> put version (SOURCE_FILES) -> build."""
        store_name = stage.name.removeprefix("pry-")
        aid = f"{org}~{store_name}"
        meta = _json.loads((stage / ".actor" / "actor.json").read_text())
        version = meta.get("version", "1.0")

        import tempfile as _tf

        def api(method, path, payload=None):
            # Large payloads (SOURCE_FILES) exceed argv limits -> @file form
            cmd = ["curl", "-sfm", "300", "-X", method,
                   "-H", f"Authorization: Bearer {token}",
                   "-H", "Content-Type: application/json"]
            if payload is not None:
                pf = _tf.NamedTemporaryFile("w", suffix=".json", delete=False)
                _json.dump(payload, pf)
                pf.close()
                cmd += ["--data-binary", f"@{pf.name}"]
            try:
                return _sp.run(cmd + [f"https://api.apify.com/v2{path}"],
                               capture_output=True, text=True)
            finally:
                if payload is not None:
                    os.unlink(pf.name)

        chk = api("GET", f"/acts/{aid}")
        if chk.returncode != 0:
            cr = api("POST", "/acts", {
                "name": store_name,
                "title": meta.get("title", store_name),
                "description": meta.get("description", ""),
            })
            if cr.returncode != 0:
                return False, f"create failed: {(cr.stdout or cr.stderr)[-200:]}"

        # Collect staged source files (relative paths from stage root)
        source_files = []
        for fpath in sorted(stage.rglob("*")):
            if fpath.is_file() and "__pycache__" not in str(fpath):
                rel = str(fpath.relative_to(stage))
                try:
                    content = fpath.read_text()
                except UnicodeDecodeError:
                    import base64 as _b64
                    content = _b64.b64encode(fpath.read_bytes()).decode()
                    rel += "|base64"
                source_files.append({"name": rel, "content": content,
                                     "format": "TEXT"})
        ver_payload = {
            "versionNumber": version,
            "sourceType": "SOURCE_FILES",
            "sourceFiles": source_files,
            "buildTag": meta.get("buildTag", "latest"),
        }
        uv = api("PUT", f"/acts/{aid}/versions/{version}", ver_payload)
        if uv.returncode != 0:
            return False, f"version upload failed: {(uv.stdout or uv.stderr)[-300:]}"
        build = api("POST", f"/acts/{aid}/builds?version={version}&wait=180")
        build_ok = build.returncode == 0
        detail = (build.stdout or "")[-200:] if not build_ok else "built"

        # Metadata update (PUT - PATCH is 405 on this endpoint)
        api("PUT", f"/acts/{aid}", {
            "title": meta.get("title", store_name),
            "description": meta.get("description", ""),
        })
        return build_ok, detail

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
