#!/usr/bin/env python3
"""guardian_scan.py — the guardian gate's rule engine (policy, stdlib only).

Holds the five rule families (test_deletion, ci_modification,
process_execution, eval_dynamic, scope_creep) and their verdicts. The policy
constants are PINNED here so the gate cannot be neutralised by a change under
review — see check-guardian.py for the full policy statement.

Split out of check-guardian.py for the ≤200-line cap; guardian_core.py holds
the diff mechanism and shared types.
"""

from __future__ import annotations

from guardian_core import (
    CI_PATH_RE,
    DEF_TEST_RE,
    EVAL_RE,
    PROCESS_EXEC_RE,
    R_CI_MODIFICATION,
    R_EVAL_DYNAMIC,
    R_PROCESS_EXEC,
    R_SCOPE_CREEP,
    R_TEST_DELETION,
    TEST_PATH_ANY_RE,
    DocTracker,
    Finding,
)


def scan(files, max_files, max_lines, strict_scope):
    """Apply every rule family. Returns (findings, stats)."""
    findings: list[Finding] = []
    total_added = 0
    changed = set()

    removed_tests = []  # (path, lineno) of removed `def test_`
    deleted_test_files = []  # paths of deleted tests/**
    added_tests = 0

    for f in files:
        path = f["path"]
        added_lines = f["added"]
        changed.add(path)
        total_added += len(added_lines) + len(f["removed"])

        # ── rule 1 housekeeping: classify test churn ─────────────────────────
        if f["deleted"] and TEST_PATH_ANY_RE.search(path):
            deleted_test_files.append(path)
        for lineno, text in f["removed"]:
            if DEF_TEST_RE.search(text):
                removed_tests.append((path, lineno))
        for _lineno, text in added_lines:
            if DEF_TEST_RE.search(text):
                added_tests += 1

        # ── rule 2: CI-config modification ───────────────────────────────────
        if CI_PATH_RE.search(path):
            findings.append(
                Finding(
                    R_CI_MODIFICATION,
                    path,
                    0,
                    "edit to a CI workflow (gate config must come from the base branch)",
                    blocking=False,
                )
            )

        is_test_file = bool(TEST_PATH_ANY_RE.search(path))
        docs = DocTracker()

        # ── rule 3 + 4: process execution / dynamic eval on ADDED lines ──────
        # Doc lines (comments / docstrings) are skipped so the gate does not
        # flag its own rule documentation; real call lines are never excluded.
        for lineno, text in added_lines:
            if docs.consume(text):
                continue
            if PROCESS_EXEC_RE.search(text):
                findings.append(
                    Finding(
                        R_PROCESS_EXEC,
                        path,
                        lineno,
                        f"new shell/exec call: {text.strip()[:120]}",
                        blocking=True,
                    )
                )
            if EVAL_RE.search(text) and not is_test_file:
                findings.append(
                    Finding(
                        R_EVAL_DYNAMIC,
                        path,
                        lineno,
                        f"new dynamic eval/exec in non-test source: {text.strip()[:120]}",
                        blocking=True,
                    )
                )

    # ── rule 1 verdict: deletion without a compensating test ─────────────────
    test_deleted = bool(removed_tests) or bool(deleted_test_files)
    if test_deleted and added_tests == 0:
        for p in deleted_test_files:
            findings.append(
                Finding(R_TEST_DELETION, p, 0, "test file deleted with no new test added", True)
            )
        for path, lineno in removed_tests:
            findings.append(
                Finding(
                    R_TEST_DELETION,
                    path,
                    lineno,
                    "removed `def test_` with no new test added",
                    True,
                )
            )

        # ── rule 2 escalation: CI edit + test deletion = blocked ─────────────
        for fnd in findings:
            if fnd.rule == R_CI_MODIFICATION:
                fnd.blocking = True
                fnd.detail += " + tests deleted in the same diff"

    # ── rule 5: scope creep ──────────────────────────────────────────────────
    n_files = len(changed)
    if n_files > max_files or total_added > max_lines:
        findings.append(
            Finding(
                R_SCOPE_CREEP,
                "<diff>",
                0,
                f"diff touches {n_files} files / {total_added} lines "
                f"(limits: {max_files} files, {max_lines} lines)",
                strict_scope,
            )
        )

    stats = {
        "files": n_files,
        "lines": total_added,
        "tests_removed": len(removed_tests) + len(deleted_test_files),
        "tests_added": added_tests,
    }
    return findings, stats
