#!/usr/bin/env python3
"""check-guardian.py — dangerous-diff scanner (self-contained, stdlib only).

POLICY
------
An agent (or a human) must never be able to weaken the fleet silently. This
gate reads a diff and refuses changes that hide a regression instead of fixing
one (modelled on OpenArbiter/arbiter's "dangerous-diff auto-reviewer"):

  test_deletion      removed `def test_` or deleted `tests/**` with no
                     compensating new test. FAIL.
  ci_modification    `.forgejo/workflows/**` or `.github/workflows/**` edits.
                     WARN; FAILs when the diff also deletes tests ("delete the
                     check, then loosen the gate").
  process_execution  new `subprocess.*(shell=True)`, `os.system(`, `os.exec*`,
                     `os.popen(`. FAIL.
  eval_dynamic       new dynamic eval/exec calls in non-test source. FAIL.
  scope_creep        > N files or M lines (default 40 / 1500). WARN; escalate
                     with --strict-scope.

WHY GATE CONFIG MUST COME FROM THE BASE BRANCH
----------------------------------------------
A gate that reads its own thresholds from the tree under review can be
neutralised by the change it should judge: edit the config, and the gate
passes. The policy (rule set, thresholds) is PINNED in scripts/guardian_scan.py
and the CI job runs it against the diff only — never an actor-authored config
read from HEAD. Changing those constants is a visible, reviewed act; a PR
silently editing the gate is not. Treat this as required-check infrastructure.

Split for the ≤200-line cap: guardian_core.py (diff parse/load, regexes,
Finding), guardian_scan.py (scan rules). This module is the CLI + verdict.

USAGE
-----
  python3 scripts/check-guardian.py                 # scan `git diff --cached`
  python3 scripts/check-guardian.py --diff <file>   # scan a saved diff

Exit codes: 0 = pass (warnings allowed), 1 = blocked, 2 = could not measure.
"""

from __future__ import annotations

import argparse
import sys

from guardian_core import load_diff, parse_diff
from guardian_scan import scan

BLOCKED = 1
UNMEASURED = 2


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Guardian: fail on dangerous diffs (test deletion, CI "
        "edits, new shell/exec, dynamic eval, scope creep).",
    )
    parser.add_argument(
        "--diff",
        default=None,
        help="Path to a unified diff to scan (default: `git diff --cached`).",
    )
    parser.add_argument("--max-files", type=int, default=40)
    parser.add_argument("--max-lines", type=int, default=1500)
    parser.add_argument(
        "--strict-scope",
        action="store_true",
        help="Escalate scope_creep from WARN to BLOCK.",
    )
    args = parser.parse_args(argv)

    text = load_diff(args.diff)
    if text is None:
        print("[ERROR] guardian could not read a diff — refusing to fail open.", file=sys.stderr)
        return UNMEASURED

    findings, stats = scan(parse_diff(text), args.max_files, args.max_lines, args.strict_scope)

    print(
        f"guardian: {stats['files']} file(s), {stats['lines']} changed line(s); "
        f"tests removed={stats['tests_removed']} added={stats['tests_added']}"
    )
    for fnd in findings:
        print(fnd.render())

    blocked = [f for f in findings if f.blocking]
    if blocked:
        print(f"\n❌ guardian BLOCKED {len(blocked)} finding(s). Fix or get Lead approval.")
        return BLOCKED

    if findings:
        print("\n⚠️  guardian passed with warnings (no blocking finding).")
    else:
        print("✅ guardian: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
