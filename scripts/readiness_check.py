#!/usr/bin/env python3
"""Go-live readiness check: assert the app is ready to ship.
Read-only. Offline. Deterministic. Prints PASS/FAIL per check and exits
non-zero if any check fails. It mutates nothing and is safe to run in CI.
Usage:
    python3 scripts/readiness_check.py
Exit code:
    0  every readiness check passed  → app is go-live ready
    1  one or more checks failed     → see FAIL lines / backlog
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent


def _run(args: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
    """Run a command from ROOT, capturing output. Never raises on exit code."""
    return subprocess.run(  # noqa: S603
        args, cwd=ROOT, capture_output=True, text=True, timeout=120, **kw
    )


def check_import_smoke() -> tuple[bool, str]:
    """1. The app constructs: import the ASGI app and count OpenAPI paths."""
    code = (
        "import warnings; warnings.filterwarnings('ignore');"
        "from pry.api.api import app;"
        "paths = app.openapi().get('paths', {});"
        "print(len(paths)); assert len(paths) > 0, 'no openapi paths'"
    )
    res = _run([sys.executable, "-c", code])
    if res.returncode != 0:
        return False, f"import/openapi failed: {res.stderr.strip().splitlines()[-1:]}"
    return True, f"app imports, openapi paths={res.stdout.strip()}"


def check_gates_present() -> tuple[bool, str]:
    """2. Required gate scripts exist and are runnable via python3."""
    gates = [
        "scripts/check-structure.py",
        "scripts/check-antipatterns.py",
        "scripts/check-monkeypatch.py",
        "scripts/check-guardian.py",
    ]
    missing = [g for g in gates if not (ROOT / g).is_file()]
    if missing:
        return False, f"missing gate scripts: {missing}"
    unreadable = []
    for g in gates:
        res = _run(["python3", g, "--help"])
        if res.returncode != 0:
            unreadable.append(g)
    if unreadable:
        return False, f"gates not runnable (python3 --help != 0): {unreadable}"
    return True, f"all {len(gates)} gates present and runnable"


def check_ci_wired() -> tuple[bool, str]:
    """3. CI workflow parses and declares the required jobs."""
    ci = ROOT / ".forgejo/workflows/ci.yml"
    if not ci.is_file():
        return False, "missing .forgejo/workflows/ci.yml"
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        logging.warning("readiness: handled %s", "ImportError")
        raw = ci.read_text()
        required = [
            "lint",
            "typecheck",
            "test",
            "structure-gate",
            "security",
            "secrets",
            "guardian",
        ]
        present = {j for j in required if f"{j}:" in raw}
        missing = [j for j in required if j not in present]
        if missing:
            return False, f"ci.yml jobs missing (no yaml): {missing}"
        return True, f"ci.yml parsed as text, all {len(required)} jobs present"
    try:
        doc = yaml.safe_load(ci.read_text())
    except Exception as exc:  # noqa: BLE001
        logging.warning("readiness: handled %s", "Exception")
        return False, f"ci.yml does not parse: {exc}"
    jobs = set((doc or {}).get("jobs") or {})
    required = [
        "lint",
        "typecheck",
        "test",
        "structure-gate",
        "security",
        "secrets",
        "guardian",
    ]
    missing = [j for j in required if j not in jobs]
    if missing:
        return False, f"ci.yml parses but jobs missing: {missing}"
    return True, f"ci.yml parses, all {len(required)} required jobs present"


def check_backtest_offline() -> tuple[bool, str]:
    """4. Ladder backtest runs offline and its fixture exists."""
    fixture = ROOT / "data/ladder_baseline.json"
    if not fixture.is_file():
        return False, f"missing backtest fixture: {fixture.relative_to(ROOT)}"
    res = _run(["python3", "scripts/backtest_ladder.py", "--offline"], env=_offline_env())
    if res.returncode != 0:
        tail = (res.stdout + res.stderr).strip().splitlines()[-1:]
        return False, f"backtest --offline exit {res.returncode}: {tail}"
    return True, "backtest_ladder.py --offline exit 0 (fixture present)"


def _offline_env() -> dict[str, str]:
    """Environment that forbids accidental network use on the offline path."""
    env = dict(os.environ)
    env.setdefault("PRY_URL", "http://127.0.0.1:1")
    env.setdefault("NO_PROXY", "*")
    return env


def check_apify_manifest() -> tuple[bool, str]:
    """5. Apify actor.json parses and every referenced file exists."""
    manifest = ROOT / ".actor/actor.json"
    if not manifest.is_file():
        return False, "missing .actor/actor.json"
    try:
        doc = json.loads(manifest.read_text())
    except Exception as exc:  # noqa: BLE001
        logging.warning("readiness: handled %s", "Exception")
        return False, f".actor/actor.json does not parse: {exc}"
    refs = [doc.get("dockerfile"), doc.get("output")]
    refs += list((doc.get("storages") or {}).values())
    refs += [v for k, v in (doc.get("input") or {}).items() if k.endswith("Schema")]
    missing = []
    for ref in refs:
        if not ref or not isinstance(ref, str):
            continue
        target = (manifest.parent / ref).resolve()
        if not target.is_file():
            missing.append(ref)
    if missing:
        return False, f"actor.json references missing files: {missing}"
    return True, f"actor.json parses, {len([r for r in refs if r])} refs resolved"


def check_doc_claims() -> tuple[bool, str]:
    """6. Documented claims match the code."""
    res = _run(["python3", "scripts/check-doc-claims.py"])
    if res.returncode != 0:
        tail = (res.stdout + res.stderr).strip().splitlines()[-1:]
        return False, f"check-doc-claims.py exit {res.returncode}: {tail}"
    return True, "check-doc-claims.py exit 0"


CHECKS = [
    ("1. import/start smoke", check_import_smoke),
    ("2. gates present", check_gates_present),
    ("3. CI wired", check_ci_wired),
    ("4. backtest offline", check_backtest_offline),
    ("5. apify manifest", check_apify_manifest),
    ("6. docs claims", check_doc_claims),
]


def main() -> int:
    print("== GO-LIVE READINESS CHECK ==")
    print(f"root: {ROOT}")
    failures = 0
    for name, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "suppressed %s in main (readiness_check.py:185): %s",
                "Exception",
                exc,
            )
            ok, detail = False, f"check raised: {exc!r}"
        status = "PASS" if ok else "FAIL"
        if not ok:
            failures += 1
        print(f"[{status}] {name}: {detail}")
    print(f"== {len(CHECKS) - failures}/{len(CHECKS)} passed ==")
    if failures:
        print(f"== NOT READY: {failures} check(s) failed (readiness backlog) ==")
        return 1
    print("== READY TO SHIP ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
